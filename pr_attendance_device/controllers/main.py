import json
from datetime import datetime

import pytz

from odoo import fields, http
from odoo.http import request, Response


class Icloud(http.Controller):
    def _json_response(self, payload, status=200):
        return Response(
            json.dumps(payload, default=str),
            status=status,
            content_type='application/json; charset=utf-8',
        )

    def _truthy(self, value):
        return str(value).strip().lower() in ('1', 'true', 'yes', 'y', 'on')

    def _get_payload(self, kw):
        payload = request.httprequest.get_json(silent=True)
        if isinstance(payload, dict):
            return payload
        raw_body = request.httprequest.data
        if raw_body:
            try:
                payload = json.loads(raw_body.decode('utf-8'))
                if isinstance(payload, dict):
                    return payload
            except Exception:
                pass
        return dict(kw)

    def _resolve_device(self, payload):
        Device = request.env['attendance.device'].sudo()
        device_id = payload.get('device_id')
        serial_number = (
            payload.get('serial_number')
            or payload.get('serialnumber')
            or payload.get('SN')
            or payload.get('sn')
        )

        if device_id:
            device = Device.browse(int(device_id)).exists()
            if not device:
                raise ValueError('No attendance device found for device_id=%s.' % device_id)
            return device

        if serial_number:
            device = Device.search([('serialnumber', '=', serial_number)], limit=1)
            if not device:
                raise ValueError('No attendance device found for serial_number=%s.' % serial_number)
            return device

        return Device

    def _single_record_or_error(self, records, label):
        if not records:
            raise ValueError('No %s found for the provided payload.' % label)
        if len(records) > 1:
            raise ValueError('Multiple %s records matched. Please send device_id or serial_number.' % label)
        return records

    def _resolve_device_user(self, payload, device):
        DeviceUser = request.env['attendance.device.user'].sudo().with_context(active_test=False)
        domain = []
        if device:
            domain.append(('device_id', '=', device.id))

        device_user_id = payload.get('device_user_id')
        if device_user_id:
            user = DeviceUser.browse(int(device_user_id)).exists()
            if not user:
                raise ValueError('No attendance device user found for device_user_id=%s.' % device_user_id)
            if device and user.device_id != device:
                raise ValueError('device_user_id=%s does not belong to device_id=%s.' % (device_user_id, device.id))
            return user

        pin = payload.get('pin') or payload.get('machine_user_id') or payload.get('user_id')
        if pin:
            return self._single_record_or_error(
                DeviceUser.search(domain + [('user_id', '=', str(pin))]),
                'attendance device user',
            )

        uid = payload.get('uid')
        if uid:
            return self._single_record_or_error(
                DeviceUser.search(domain + [('uid', '=', int(uid))]),
                'attendance device user',
            )

        employee_id = payload.get('employee_id')
        if employee_id:
            return self._single_record_or_error(
                DeviceUser.search(domain + [('employee_id', '=', int(employee_id))]),
                'attendance device user',
            )

        barcode = payload.get('barcode') or payload.get('employee_barcode')
        if barcode:
            employee = request.env['hr.employee'].sudo().search([('barcode', '=', str(barcode))], limit=1)
            if not employee:
                raise ValueError('No employee found for barcode=%s.' % barcode)
            return self._single_record_or_error(
                DeviceUser.search(domain + [('employee_id', '=', employee.id)]),
                'attendance device user',
            )

        raise ValueError('Send one of: device_user_id, pin/user_id, uid, employee_id, or barcode.')

    def _get_status_code(self, payload):
        status = payload.get('status') if 'status' in payload else payload.get('punch')
        if status not in (None, ''):
            return int(status)

        punch_type = (
            payload.get('punch_type')
            or payload.get('type')
            or payload.get('action')
            or payload.get('attendance_type')
        )
        normalized = str(punch_type or '').strip().lower().replace('-', '_').replace(' ', '_')
        if normalized in ('check_in', 'checkin', 'in', 'signin', 'sign_in'):
            return 0
        if normalized in ('check_out', 'checkout', 'out', 'signout', 'sign_out'):
            return 1
        raise ValueError('Send punch_type as check_in/check_out, or send numeric status/punch.')

    def _resolve_attendance_state(self, device, status_code):
        state_line = device.attendance_device_state_line_ids.filtered(lambda line: line.code == status_code)[:1]
        if state_line:
            return state_line.attendance_state_id

        state = request.env['attendance.state'].sudo().search([('code', '=', status_code)], limit=1)
        if not state:
            raise ValueError('No attendance.state configured for status code %s.' % status_code)
        return state

    def _parse_timestamp(self, payload, device):
        raw_timestamp = payload.get('timestamp') or payload.get('time') or payload.get('punch_time')
        if not raw_timestamp:
            raise ValueError('Send timestamp/time in format YYYY-MM-DD HH:MM:SS or ISO datetime.')

        value = str(raw_timestamp).strip()
        iso_value = value[:-1] + '+00:00' if value.endswith('Z') else value
        timestamp = None
        for parser in (
            lambda val: datetime.fromisoformat(val),
            lambda val: datetime.strptime(val, '%Y-%m-%d %H:%M:%S'),
            lambda val: datetime.strptime(val, '%Y-%m-%dT%H:%M:%S'),
        ):
            try:
                timestamp = parser(iso_value)
                break
            except ValueError:
                continue

        if not timestamp:
            raise ValueError('Invalid timestamp format: %s.' % raw_timestamp)

        if timestamp.tzinfo:
            return timestamp.astimezone(pytz.UTC).replace(tzinfo=None)

        if self._truthy(payload.get('is_utc') or payload.get('utc')):
            return timestamp

        timezone_name = payload.get('timezone') or device.tz or 'Asia/Riyadh'
        return device.convert_local_to_utc(timestamp, timezone_name, naive=True)

    @http.route(['/api/attendance/punch', '/api/attendance/punch/'], type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def create_attendance_punch(self, **kw):
        if request.httprequest.method == 'GET':
            return self._json_response({
                'success': True,
                'message': 'Send a POST request with device/user, punch_type, and timestamp to create a punch.',
                'example': {
                    'device_id': 1,
                    'pin': '1001',
                    'punch_type': 'check_in',
                    'timestamp': '2026-06-02 08:15:00',
                },
            })

        payload = self._get_payload(kw)
        try:
            device = self._resolve_device(payload)
            device_user = self._resolve_device_user(payload, device)
            device = device or device_user.device_id
            status_code = self._get_status_code(payload)
            attendance_state = self._resolve_attendance_state(device, status_code)
            timestamp = fields.Datetime.to_datetime(self._parse_timestamp(payload, device))

            UserAttendance = request.env['user.attendance'].sudo()
            existing = UserAttendance.search([
                ('device_id', '=', device.id),
                ('user_id', '=', device_user.id),
                ('timestamp', '=', timestamp),
            ], limit=1)
            if existing:
                if existing.status != status_code:
                    return self._json_response({
                        'success': False,
                        'error': 'A punch already exists for this device user and timestamp with a different status.',
                        'existing_id': existing.id,
                        'existing_status': existing.status,
                    }, status=409)
                return self._json_response({
                    'success': True,
                    'duplicate': True,
                    'id': existing.id,
                    'device_id': device.id,
                    'device_user_id': device_user.id,
                    'employee_id': device_user.employee_id.id,
                    'timestamp': existing.timestamp,
                    'status': existing.status,
                    'type': existing.type,
                    'synced': existing.synced,
                })

            attendance = UserAttendance.create({
                'device_id': device.id,
                'user_id': device_user.id,
                'timestamp': timestamp,
                'status': status_code,
                'attendance_state_id': attendance_state.id,
            })

            if self._truthy(payload.get('sync')):
                attendance._sync_attendance()

            return self._json_response({
                'success': True,
                'id': attendance.id,
                'device_id': device.id,
                'device_user_id': device_user.id,
                'employee_id': device_user.employee_id.id,
                'timestamp': attendance.timestamp,
                'status': attendance.status,
                'type': attendance.type,
                'synced': attendance.synced,
                'hr_attendance_id': attendance.hr_attendance_id.id,
            }, status=201)
        except ValueError as error:
            return self._json_response({'success': False, 'error': str(error)}, status=400)
        except Exception as error:
            request.env.cr.rollback()
            return self._json_response({'success': False, 'error': str(error)}, status=500)

    @http.route('/iclock/cdata', type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def returned_data_from_device(self, SN, **kw):
        method = request.httprequest.method
        table = kw.get('table', None)
        try:
            data = request.httprequest.data.decode('utf-8')
        except Exception:
            data = request.httprequest.data.decode('gb18030')
        res = request.env['attendance.device'].sudo().process_data_from_device(method, SN, data, table)
        return Response(res)

    @http.route('/iclock/getrequest', type='http', auth='public', methods=['GET'], csrf=False)
    def getrequest(self, SN, **kw):
        res = request.env['attendance.device'].sudo().process_getrequest(SN)
        return Response(res)

    @http.route('/iclock/devicecmd', type='http', auth='public', methods=['POST'], csrf=False)
    def returned_cmd_from_device(self, SN, **kw):
        try:
            data = request.httprequest.data.decode('utf-8')
        except Exception:
            data = request.httprequest.data.decode('gb18030')
        res = request.env['attendance.device'].sudo().process_returned_command_results(SN, data)
        return Response(res)
