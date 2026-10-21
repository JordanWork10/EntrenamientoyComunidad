"""
V123 - Respuestas profesionales ante incidencias.

Permite que el Profesional involucrado presente
su versión de los hechos durante una investigación.

Reglas:
- Solo el Profesional de la reserva puede responder.
- Una respuesta por incidencia.
- No se admiten respuestas después de la resolución.
- Las declaraciones quedan registradas sin edición.
- El Profesional no puede cambiar el estado administrativo.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import (
    get_object_or_404,
    redirect,
)
from django.views.decorators.http import require_POST

from .models import (
    BookingSessionIncident,
    BookingIncidentProfessionalResponse,
)


# =====================================================
# V123 - ENVIAR ANTECEDENTES DEL PROFESIONAL
# =====================================================

@login_required(login_url='accounts:login')
@require_POST
def submit_professional_incident_response(request, booking_id):

    # -------------------------------------------------
    # 1. OBTENER DECLARACIÓN
    # -------------------------------------------------

    statement = (
        request.POST.get('statement') or ''
    ).strip()

    # -------------------------------------------------
    # 2. VALIDAR LONGITUD
    # -------------------------------------------------

    if len(statement) < 20 or len(statement) > 3000:

        messages.error(
            request,
            'Tu declaración debe contener entre '
            '20 y 3000 caracteres.'
        )

        return redirect(
            'bookings:professional_incident_status',
            booking_id=booking_id
        )

    # -------------------------------------------------
    # 3. INICIAR TRANSACCIÓN
    # -------------------------------------------------

    with transaction.atomic():

        # Buscar la incidencia verificando que
        # pertenezca al Profesional autenticado.

        incident = get_object_or_404(
            BookingSessionIncident.objects
            .select_for_update(),

            review__booking_id=booking_id,

            review__booking__professional_profile__user=(
                request.user
            ),
        )

        # -------------------------------------------------
        # 4. COMPROBAR ESTADO ADMINISTRATIVO
        # -------------------------------------------------

        allowed_statuses = (
            BookingSessionIncident.Status.OPEN,
            BookingSessionIncident.Status.IN_REVIEW,
        )

        if incident.status not in allowed_statuses:

            messages.error(
                request,
                'Esta incidencia ya fue resuelta '
                'y no admite nuevas declaraciones.'
            )

            return redirect(
                'bookings:professional_incident_status',
                booking_id=booking_id
            )

        # -------------------------------------------------
        # 5. EVITAR RESPUESTAS DUPLICADAS
        # -------------------------------------------------

        already_submitted = (
            BookingIncidentProfessionalResponse.objects
            .filter(
                incident=incident
            )
            .exists()
        )

        if already_submitted:

            messages.warning(
                request,
                'Ya presentaste tus antecedentes '
                'para esta incidencia.'
            )

            return redirect(
                'bookings:professional_incident_status',
                booking_id=booking_id
            )

        # -------------------------------------------------
        # 6. REGISTRAR DECLARACIÓN
        # -------------------------------------------------

        response = BookingIncidentProfessionalResponse(
            incident=incident,
            submitted_by=request.user,
            statement=statement,
        )

        # El modelo ejecuta sus validaciones
        # antes de guardar la declaración.

        response.save()

        # -------------------------------------------------
        # 7. CONFIRMAR REGISTRO
        # -------------------------------------------------

        messages.success(
            request,
            'Tus antecedentes fueron registrados '
            'correctamente y quedaron disponibles '
            'para la revisión administrativa.'
        )

    # -------------------------------------------------
    # 8. VOLVER AL SEGUIMIENTO
    # -------------------------------------------------

    return redirect(
        'bookings:professional_incident_status',
        booking_id=booking_id
    )