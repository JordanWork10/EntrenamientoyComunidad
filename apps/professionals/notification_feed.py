"""
V128 - Novedades del Centro Profesional.

La misma función alimenta el dashboard y las rutas de lectura para
que la lista de claves autorizadas no pueda diferir de la mostrada.
No crea ni modifica reservas, historiales o incidencias.
"""

from django.core.exceptions import PermissionDenied

from apps.bookings.models import Booking, BookingHistory
from apps.bookings.incident_notifications import get_session_incident_updates

from .models import ProfessionalProfile


def get_professional_updates_for(user):
    """Devuelve las 6 novedades actuales del Profesional autenticado."""

    if user is None or not getattr(user, 'is_authenticated', False):
        raise PermissionDenied('Debes iniciar sesión.')

    professional_profile = getattr(user, 'professional_profile', None)
    if (
        professional_profile is None
        or professional_profile.verification_status
        != ProfessionalProfile.VerificationStatus.VERIFIED
    ):
        raise PermissionDenied('Necesitas un Perfil Profesional verificado.')

    # =====================================================
    # NOVEDADES PROFESIONALES
    # =====================================================
    #
    # Las novedades de reservas se construyen desde BookingHistory.
    # Las incidencias se consultan desde los modelos de V123,
    # sin crear otras fuentes de verdad ni nuevas migraciones.
    #
    # Solo mostramos cambios originados por el Miembro:
    # - solicitud nueva que todavía sigue Pendiente;
    # - cancelación realizada por el Miembro.
    #
    # Los cambios hechos por el propio Profesional no se muestran
    # como novedad para él mismo.

    professional_history_events = (
        BookingHistory.objects
        .filter(
            booking__professional_profile=professional_profile,
            action__in=[
                BookingHistory.Action.CREATED,
                BookingHistory.Action.CANCELLED,
            ],
            changed_by__isnull=False,
        )
        .exclude(
            changed_by=user
        )
        .select_related(
            'booking',
            'booking__booked_by',
            'booking__service',
            'changed_by',
        )
        .order_by(
            '-created_at',
            '-id',
        )[:40]
    )

    booking_updates = []
    seen_booking_ids = set()

    for event in professional_history_events:

        booking = event.booking

        # Una sola novedad vigente por reserva.
        if booking.id in seen_booking_ids:
            continue

        member = booking.booked_by
        member_name = (
            member.get_full_name()
            or member.email
        )

        if event.action == BookingHistory.Action.CREATED:

            # Si la solicitud ya fue confirmada/cancelada, no mostramos
            # una tarjeta antigua de "nueva solicitud".
            if booking.status != Booking.Status.PENDING:
                continue

            kind = 'request'
            title = f'{member_name} envió una nueva solicitud'
            summary = (
                f'Quiere reservar {booking.service_name_snapshot}.'
            )
            reason = ''

        elif event.action == BookingHistory.Action.CANCELLED:

            # Aquí solo llegan cancelaciones realizadas por el Miembro
            # porque los cambios del propio Profesional fueron excluidos.
            if booking.status != Booking.Status.CANCELLED:
                continue

            previous_status = (
                (event.previous_data or {})
                .get('status')
            )

            kind = 'cancelled'

            if previous_status == Booking.Status.PENDING:
                title = f'{member_name} canceló su solicitud'
                summary = (
                    f'La solicitud para {booking.service_name_snapshot} '
                    'ya no requiere respuesta.'
                )
            else:
                title = f'{member_name} canceló su reserva'
                summary = (
                    f'La sesión de {booking.service_name_snapshot} '
                    'ya no se realizará.'
                )

            reason = (
                event.reason
                or booking.cancellation_reason
                or ''
            )

        else:
            continue

        booking_updates.append(
            {
                'key': f'booking-history-{event.id}',
                'kind': kind,
                'title': title,
                'summary': summary,
                'reason': reason,
                'booking': booking,
                'member': member,
                'created_at': event.created_at,
            }
        )

        seen_booking_ids.add(booking.id)

    # =====================================================
    # V123 - INTEGRAR NOVEDADES DE INCIDENCIAS
    # =====================================================
    # No reemplaza las novedades antiguas. La función de bookings
    # filtra las incidencias del Profesional autenticado y devuelve
    # una novedad vigente por incidencia con clave propia y enlace.

    incident_updates = get_session_incident_updates(
        user,
        'professional',
        limit=30,
    )

    # Reservas e incidencias se ordenan juntas por fecha real.
    # Conservamos el límite original de seis tarjetas del panel.
    professional_updates = booking_updates + incident_updates
    professional_updates.sort(
        key=lambda update: (update['created_at'], update['key']),
        reverse=True,
    )
    professional_updates = professional_updates[:6]

    return professional_updates

