from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.professionals.models import ProfessionalProfile

from .models import (
    Booking,
    BookingHistory,
)




def expire_pending_bookings(
    *,
    professional_profile=None,
    booked_by=None,
):
    """
    Cierra automáticamente las solicitudes que continúan
    Pendientes cuando ya alcanzaron su fecha y hora de inicio.

    Pendiente -> Vencida

    La transición:
    - deja de bloquear el horario;
    - conserva trazabilidad en BookingHistory;
    - se registra como cambio realizado por el Sistema;
    - puede limitarse a un Profesional o a un Miembro.
    """

    local_now = timezone.localtime(
        timezone.now()
    )

    current_date = local_now.date()
    current_time = (
        local_now
        .time()
        .replace(tzinfo=None)
    )

    candidates = (
        Booking.objects
        .filter(
            status=Booking.Status.PENDING,
        )
        .filter(
            Q(
                session_date__lt=current_date
            )
            |
            Q(
                session_date=current_date,
                start_time__lte=current_time,
            )
        )
    )

    if professional_profile is not None:
        candidates = candidates.filter(
            professional_profile=(
                professional_profile
            )
        )

    if booked_by is not None:
        candidates = candidates.filter(
            booked_by=booked_by
        )

    expired_count = 0

    with transaction.atomic():

        pending_bookings = list(
            candidates
            .select_for_update()
            .select_related(
                'booked_by',
                'professional_profile',
                'service',
            )
            .order_by(
                'session_date',
                'start_time',
            )
        )

        for booking in pending_bookings:

            # Puede haber cambiado de estado mientras se esperaba
            # el bloqueo de la fila.
            if (
                booking.status
                != Booking.Status.PENDING
            ):
                continue

            previous_data = (
                booking.audit_snapshot()
            )

            booking.status = (
                Booking.Status.EXPIRED
            )

            booking.save(
                update_fields=[
                    'status',
                    'updated_at',
                ]
            )

            BookingHistory.objects.create(
                booking=booking,
                action=(
                    BookingHistory
                    .Action
                    .EXPIRED
                ),
                previous_data=previous_data,
                new_data=(
                    booking.audit_snapshot()
                ),
                changed_by=None,
                reason=(
                    'La solicitud venció automáticamente '
                    'al alcanzar la hora de inicio sin haber '
                    'sido respondida por el Profesional.'
                ),
            )

            expired_count += 1

    return expired_count


BLOCKING_BOOKING_STATUSES = [
    Booking.Status.PENDING,
    Booking.Status.CONFIRMED,
]


def get_available_slots(
    service,
    target_date
):
    """
    Devuelve los bloques generados para una fecha excluyendo
    aquellos que ya se encuentran ocupados por una reserva
    Pendiente o Confirmada.

    No crea registros.
    """

    expire_pending_bookings(
        professional_profile=(
            service.professional_profile
        )
    )

    generated_slots = (
        service
        .generate_reservable_slots_for_date(
            target_date
        )
    )

    if not generated_slots:
        return []

    occupied_bookings = list(
        Booking.objects
        .filter(
            professional_profile=(
                service.professional_profile
            ),
            session_date=target_date,
            status__in=(
                BLOCKING_BOOKING_STATUSES
            ),
        )
        .only(
            'start_time',
            'end_time',
        )
    )

    available_slots = []

    for slot in generated_slots:

        overlaps = any(
            (
                booking.start_time
                < slot['end_time']
            )
            and (
                booking.end_time
                > slot['start_time']
            )
            for booking in occupied_bookings
        )

        if not overlaps:
            available_slots.append(
                slot
            )

    return available_slots


def create_booking(
    *,
    user,
    service,
    session_date,
    start_time,
    end_time,
):
    """
    Crea una reserva de forma transaccional.

    Se bloquea el Perfil Profesional mientras se comprueba y
    crea la reserva, evitando que dos solicitudes atendidas por
    la aplicación reserven simultáneamente el mismo horario.

    La Booking vuelve a validar que:
    - el servicio esté publicado;
    - el bloque exista realmente;
    - no haya solapamientos;
    - el usuario no reserve su propio servicio.
    """

    with transaction.atomic():

        locked_professional = (
            ProfessionalProfile.objects
            .select_for_update()
            .get(
                pk=(
                    service
                    .professional_profile_id
                )
            )
        )

        # Refrescamos el servicio después de adquirir el bloqueo
        # para trabajar con su estado actual.
        service.refresh_from_db()

        booking = Booking(
            booked_by=user,
            service=service,
            professional_profile=(
                locked_professional
            ),
            session_date=session_date,
            start_time=start_time,
            end_time=end_time,
            status=Booking.Status.PENDING,
        )

        # Booking.save() aplica snapshot y full_clean().
        booking.save()

        BookingHistory.objects.create(
            booking=booking,
            action=(
                BookingHistory
                .Action
                .CREATED
            ),
            previous_data={},
            new_data=(
                booking.audit_snapshot()
            ),
            changed_by=user,
            reason=(
                'Reserva creada desde la '
                'selección de una sesión disponible.'
            ),
        )

        return booking
