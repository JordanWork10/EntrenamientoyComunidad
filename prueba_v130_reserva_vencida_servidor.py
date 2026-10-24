"""V130: comprueba mediante POST real al servidor que la reserva #8 vencida
no se pueda confirmar. TODAS las operaciones de la prueba se revierten.
Ejecutar: python manage.py shell -c "exec(open('prueba_v130_reserva_vencida_servidor.py', encoding='utf-8').read())"
"""
from datetime import datetime
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from apps.spaces.models import SpaceBooking

BOOKING_ID = 8
booking = SpaceBooking.objects.select_related('provider_profile__user').get(pk=BOOKING_ID)
old_status = booking.status
old_history = booking.history.count()
start = timezone.make_aware(
    datetime.combine(booking.session_date, booking.start_time),
    timezone.get_current_timezone(),
)
print('RESERVA:', BOOKING_ID)
print('FECHA Y HORA:', timezone.localtime(start).strftime('%d/%m/%Y %H:%M'))
print('ESTADO ORIGINAL:', old_status)

if old_status != SpaceBooking.Status.PENDING or timezone.localtime() < start:
    print('PRUEBA OMITIDA: La reserva no esta pendiente y vencida. No se enviaron peticiones.')
else:
    response_status = None
    redirect_url = ''
    status_inside = None
    history_inside = None
    try:
        with transaction.atomic():
            try:
                client = Client(HTTP_HOST='127.0.0.1')
                client.force_login(booking.provider_profile.user)
                response = client.post(
                    reverse('spaces:provider_confirm_booking', args=[BOOKING_ID]),
                    follow=False,
                )
                response_status = response.status_code
                redirect_url = response.get('Location', '')
                booking.refresh_from_db()
                status_inside = booking.status
                history_inside = booking.history.count()
            finally:
                # Deshacer incluso si la peticion falla o hay una excepcion.
                transaction.set_rollback(True)
    except Exception as exc:
        print('ERROR DE PRUEBA:', type(exc).__name__, str(exc))
        print('CAMBIOS DE PRUEBA: REVERTIDOS')
        raise

    booking.refresh_from_db()
    final_status = booking.status
    final_history = booking.history.count()
    blocked = (response_status == 302 and 'confirm_error=expired' in redirect_url)
    preserved = (
        old_status == status_inside == final_status
        and old_history == history_inside == final_history
    )
    print('RESPUESTA HTTP:', response_status)
    print('REDIRECCION:', redirect_url)
    print('ESTADO FINAL:', final_status)
    print('HISTORIAL ANTES/DESPUES:', old_history, '/', final_history)
    print('BLOQUEO EN SERVIDOR:', 'CORRECTO' if blocked else 'REVISAR')
    print('RESERVA INTACTA:', 'SI' if preserved else 'NO')
    print('TRANSACCION DE PRUEBA: REVERTIDA')
