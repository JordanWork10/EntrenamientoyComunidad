from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.professionals.models import ProfessionalProfile

from .models import Booking, BookingHistory


def expire_pending_bookings(
    *,
    professional_profile=None,
    booked_by=None,
):
    """Marca como vencidas las solicitudes pendientes cuyo inicio pasó."""

    local_now = timezone.localtime(timezone.now())
    current_date = local_now.date()
    current_time = local_now.time().replace(tzinfo=None)

    candidates = (
        Booking.objects
        .filter(status=Booking.Status.PENDING)
        .filter(
            Q(session_date__lt=current_date)
            | Q(
                session_date=current_date,
                start_time__lte=current_time,
            )
        )
    )

    if professional_profile is not None:
        candidates = candidates.filter(
            professional_profile=professional_profile,
        )

    if booked_by is not None:
        candidates = candidates.filter(booked_by=booked_by)

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
            .order_by('session_date', 'start_time')
        )

        for booking in pending_bookings:
            if booking.status != Booking.Status.PENDING:
                continue

            previous_data = booking.audit_snapshot()
            booking.status = Booking.Status.EXPIRED
            booking.save(update_fields=['status', 'updated_at'])

            BookingHistory.objects.create(
                booking=booking,
                action=BookingHistory.Action.EXPIRED,
                previous_data=previous_data,
                new_data=booking.audit_snapshot(),
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


def get_available_slots(service, target_date):
    """Devuelve solo los horarios que el profesional puede ofrecer.

    Una reserva pendiente o confirmada ocupa el bloque. Si el
    profesional canceló una reserva, ese intervalo sigue bloqueado
    para todos los miembros y para todos los servicios del mismo
    profesional. Una cancelación hecha por el miembro libera el bloque.
    """

    expire_pending_bookings(
        professional_profile=service.professional_profile,
    )

    generated_slots = (
        service.generate_reservable_slots_for_date(target_date)
    )

    if not generated_slots:
        return []

    occupied_intervals = list(
        Booking.blocking_for_professional(
            professional_profile_id=service.professional_profile_id,
            professional_user_id=service.professional_profile.user_id,
            session_date=target_date,
        )
        .order_by()
        .values_list('start_time', 'end_time')
    )

    available_slots = []

    for slot in generated_slots:
        overlaps = any(
            occupied_start < slot['end_time']
            and occupied_end > slot['start_time']
            for occupied_start, occupied_end in occupied_intervals
        )

        if not overlaps:
            available_slots.append(slot)

    return available_slots


def create_booking(
    *,
    user,
    service,
    session_date,
    start_time,
    end_time,
):
    """Crea la reserva bajo bloqueo del perfil profesional.

    Booking.save() vuelve a validar la disponibilidad y los horarios
    bloqueados, incluso si el usuario intenta saltarse el calendario.
    """

    with transaction.atomic():
        locked_professional = (
            ProfessionalProfile.objects
            .select_for_update()
            .get(pk=service.professional_profile_id)
        )

        service.refresh_from_db()

        booking = Booking(
            booked_by=user,
            service=service,
            professional_profile=locked_professional,
            session_date=session_date,
            start_time=start_time,
            end_time=end_time,
            status=Booking.Status.PENDING,
        )

        booking.save()

        BookingHistory.objects.create(
            booking=booking,
            action=BookingHistory.Action.CREATED,
            previous_data={},
            new_data=booking.audit_snapshot(),
            changed_by=user,
            reason=(
                'Reserva creada desde la '
                'selección de una sesión disponible.'
            ),
        )

        return booking
