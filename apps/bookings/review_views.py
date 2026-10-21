"""
V123 - Confirmación de sesiones, evaluaciones
y seguimiento administrativo de incidencias.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    Booking,
    BookingSessionReview,
    BookingSessionIncident,
)


# =====================================================
# OBTENER CONFORMIDAD DEL MIEMBRO
# =====================================================

def _owned_review(request, booking_id, lock=False):

    qs = BookingSessionReview.objects.select_related(
        'booking',
        'booking__professional_profile__user',
        'booking__booked_by'
    )

    if lock:
        qs = qs.select_for_update()

    return get_object_or_404(
        qs,
        booking_id=booking_id,
        booking__booked_by=request.user,
        booking__status=Booking.Status.COMPLETED,
    )


# =====================================================
# V123 - INFORMACIÓN PÚBLICA DE UNA INCIDENCIA
# =====================================================

def _public_incident_data(incident):
    """
    Prepara únicamente los datos que pueden consultar
    el Miembro y el Profesional involucrados.

    Nunca incluye observaciones internas,
    notas administrativas ni datos privados
    del administrador.
    """

    if incident is None:
        return None

    is_resolved = (
        incident.status
        == BookingSessionIncident.Status.RESOLVED
    )

    return {
        'status': incident.status,

        'status_label': (
            incident.get_status_display()
        ),

        'reported_at': (
            incident.review.responded_at
        ),

        'reviewed_at': (
            incident.reviewed_at
        ),

        'resolved_at': (
            incident.resolved_at
            if is_resolved
            else None
        ),

        'resolution_type_label': (
            incident.get_resolution_type_display()
            if is_resolved and incident.resolution_type
            else ''
        ),

        'resolution_summary': (
            incident.resolution_summary
            if is_resolved
            else ''
        ),
    }


# =====================================================
# MOSTRAR CONFIRMACIÓN Y EVALUACIÓN DEL MIEMBRO
# =====================================================

@login_required(login_url='accounts:login')
def review_session(request, booking_id):

    review = _owned_review(
        request,
        booking_id
    )

    # V123: buscar seguimiento administrativo
    # solamente de esta conformidad.
    incident = (
        BookingSessionIncident.objects
        .filter(review_id=review.pk)
        .first()
    )

    return render(
        request,
        'bookings/session_review.html',
        {
            'review': review,

            'booking': review.booking,

            'window_open': (
                review.status
                == BookingSessionReview.Status.PENDING
                and review.expires_at > timezone.now()
            ),

            'stars': range(1, 6),

            # Información pública del caso
            'incident_info': (
                _public_incident_data(incident)
            ),
        }
    )


# =====================================================
# CONFIRMAR QUE SE RECIBIÓ LA SESIÓN
# =====================================================

@login_required(login_url='accounts:login')
@require_POST
def confirm_session(request, booking_id):

    with transaction.atomic():

        review = _owned_review(
            request,
            booking_id,
            lock=True
        )

        if (
            review.status
            != BookingSessionReview.Status.PENDING
            or review.expires_at <= timezone.now()
        ):

            messages.warning(
                request,
                'Esta confirmación ya fue resuelta o venció.'
            )

        else:

            review.status = (
                BookingSessionReview.Status.CONFIRMED
            )

            review.responded_at = timezone.now()

            review.save(
                update_fields=[
                    'status',
                    'responded_at',
                    'updated_at'
                ]
            )

            messages.success(
                request,
                'Gracias por confirmar que recibiste la sesión. '
                'Puedes evaluarla si quieres.'
            )

    return redirect(
        'bookings:session_review',
        booking_id=booking_id
    )


# =====================================================
# REPORTAR PROBLEMA Y CREAR INCIDENCIA
# =====================================================

@login_required(login_url='accounts:login')
@require_POST
def report_session(request, booking_id):

    reason = (
        request.POST.get('issue_reason') or ''
    ).strip()

    # Validar la descripción
    if len(reason) < 10 or len(reason) > 1000:

        messages.error(
            request,
            'Explica qué ocurrió usando entre '
            '10 y 1000 caracteres.'
        )

        return redirect(
            'bookings:session_review',
            booking_id=booking_id
        )

    # Guardar conformidad e incidencia
    # dentro de una misma transacción.
    with transaction.atomic():

        review = _owned_review(
            request,
            booking_id,
            lock=True
        )

        if (
            review.status
            != BookingSessionReview.Status.PENDING
            or review.expires_at <= timezone.now()
        ):

            messages.warning(
                request,
                'El plazo para responder ya venció '
                'o ya respondiste.'
            )

        else:

            # -----------------------------------------
            # 1. REGISTRAR PROBLEMA DEL MIEMBRO
            # -----------------------------------------

            review.status = (
                BookingSessionReview.Status.REPORTED
            )

            review.issue_reason = reason
            review.responded_at = timezone.now()

            review.save(
                update_fields=[
                    'status',
                    'issue_reason',
                    'responded_at',
                    'updated_at'
                ]
            )

            # -----------------------------------------
            # 2. CREAR INCIDENCIA ADMINISTRATIVA
            # -----------------------------------------

            BookingSessionIncident.objects.get_or_create(
                review=review,
                defaults={
                    'status': (
                        BookingSessionIncident.Status.OPEN
                    ),
                }
            )

            # -----------------------------------------
            # 3. CONFIRMAR REGISTRO
            # -----------------------------------------

            messages.success(
                request,
                'Registramos el problema. '
                'Quedó pendiente de revisión por la plataforma.'
            )

    return redirect(
        'bookings:session_review',
        booking_id=booking_id
    )


# =====================================================
# EVALUAR SESIÓN CON ESTRELLAS
# =====================================================

@login_required(login_url='accounts:login')
@require_POST
def rate_session(request, booking_id):

    rating_raw = (
        request.POST.get('rating') or ''
    ).strip()

    comment = (
        request.POST.get('rating_comment') or ''
    ).strip()

    try:
        rating = int(rating_raw)

    except (TypeError, ValueError):
        rating = 0

    # -----------------------------------------
    # VALIDAR CALIFICACIÓN
    # -----------------------------------------

    if (
        rating not in (1, 2, 3, 4, 5)
        or len(comment) > 500
    ):

        messages.error(
            request,
            'Elige entre 1 y 5 estrellas '
            'y usa un comentario de hasta 500 caracteres.'
        )

        return redirect(
            'bookings:session_review',
            booking_id=booking_id
        )

    # -----------------------------------------
    # GUARDAR EVALUACIÓN
    # -----------------------------------------

    with transaction.atomic():

        review = _owned_review(
            request,
            booking_id,
            lock=True
        )

        if (
            review.status
            != BookingSessionReview.Status.CONFIRMED
        ):

            messages.error(
                request,
                'Solo puedes evaluar una sesión '
                'que confirmaste.'
            )

        elif review.rated_at is not None:

            messages.warning(
                request,
                'Esta sesión ya tiene una evaluación registrada.'
            )

        else:

            review.rating = rating
            review.rating_comment = comment
            review.rated_at = timezone.now()

            review.save(
                update_fields=[
                    'rating',
                    'rating_comment',
                    'rated_at',
                    'updated_at'
                ]
            )

            messages.success(
                request,
                '¡Gracias! Tu evaluación quedó registrada.'
            )

    return redirect(
        'bookings:session_review',
        booking_id=booking_id
    )


# =====================================================
# V123 - SEGUIMIENTO DE INCIDENCIA DEL PROFESIONAL
# =====================================================

@login_required(login_url='accounts:login')
def professional_incident_status(request, booking_id):
    """
    Permite al Profesional consultar una incidencia
    relacionada exclusivamente con sus reservas.

    Solo muestra:
    - Datos de la sesión.
    - Motivo reportado por el Miembro.
    - Estado administrativo.
    - Resolución, si existe.

    No permite modificar la incidencia.
    """

    # -----------------------------------------
    # COMPROBAR QUE LA RESERVA SEA SUYA
    # -----------------------------------------

    incident = get_object_or_404(
        BookingSessionIncident.objects.select_related(
            'review',
            'review__booking',
            'review__booking__booked_by',
            'review__booking__professional_profile__user',
        ),

        review__booking_id=booking_id,

        review__booking__professional_profile__user=(
            request.user
        ),
    )

    booking = incident.review.booking

    # -----------------------------------------
    # PREPARAR INFORMACIÓN DE CONSULTA
    # -----------------------------------------

    incident_info = _public_incident_data(
        incident
    )

    # -----------------------------------------
    # MOSTRAR SEGUIMIENTO
    # -----------------------------------------

    return render(
        request,
        'bookings/professional_incident_status.html',
        {
            'booking': booking,

            'issue_reason': (
                incident.review.issue_reason
            ),

            'incident_info': incident_info,
        }
    )