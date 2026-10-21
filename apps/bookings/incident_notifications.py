"""
V123 - Novedades de incidencias de sesiones profesionales.

Lee los registros reales existentes, sin crear ni modificar datos.
Devuelve una sola novedad (la mas reciente) por incidencia y destinatario.
La marca de revisada se integrara en el dashboard en pasos posteriores.
"""

from django.urls import reverse

from .models import BookingSessionIncident


def get_session_incident_updates(user, role, limit=30):
    """Construye novedades para 'professional' o 'member'.

    Se filtra en la base de datos por el propietario real de la reserva.
    No se incluyen observaciones internas ni declaraciones privadas en tarjetas.
    """
    if role not in ('professional', 'member'):
        raise ValueError("role debe ser 'professional' o 'member'.")

    if not user or not user.is_authenticated:
        return []

    limit = max(1, min(int(limit), 50))

    queryset = BookingSessionIncident.objects.select_related(
        'review',
        'review__booking',
        'review__booking__booked_by',
        'review__booking__professional_profile__user',
        'professional_response',
    )

    if role == 'professional':
        queryset = queryset.filter(
            review__booking__professional_profile__user=user,
        )
        url_name = 'bookings:professional_incident_status'
    else:
        queryset = queryset.filter(
            review__booking__booked_by=user,
        )
        url_name = 'bookings:session_review'

    updates = []

    for incident in queryset.order_by('-created_at')[:50]:
        booking = incident.review.booking
        member = booking.booked_by
        response = getattr(incident, 'professional_response', None)
        events = []

        if role == 'professional':
            events.append((
                incident.created_at,
                'incident_reported',
                'El miembro reportó un inconveniente',
                'Se registró un reporte relacionado con tu sesión. '
                'Revisa el motivo y presenta antecedentes si corresponde.',
            ))

        if incident.reviewed_at:
            events.append((
                incident.reviewed_at,
                'incident_in_review',
                'La plataforma inició la revisión',
                'La administración está revisando la incidencia '
                'relacionada con esta reserva.',
            ))

        # La respuesta del profesional es una novedad para el miembro,
        # no para el propio autor de la declaración.
        if role == 'member' and response is not None:
            events.append((
                response.created_at,
                'incident_response',
                'El profesional presentó sus antecedentes',
                'El profesional entregó su versión de los hechos '
                'para la revisión administrativa.',
            ))

        if (
            incident.status == BookingSessionIncident.Status.RESOLVED
            and incident.resolved_at
        ):
            events.append((
                incident.resolved_at,
                'incident_resolved',
                'La plataforma resolvió una incidencia',
                'La investigación finalizó. Puedes consultar '
                'la decisión y su explicación.',
            ))

        # No avisar al miembro sobre el reporte que él mismo presentó,
        # salvo que exista una actuación posterior.
        if not events:
            continue

        event_at, kind, title, summary = max(
            events,
            key=lambda event: event[0],
        )

        updates.append({
            'key': f'incident-{incident.pk}-{kind}',
            'kind': kind,
            'title': title,
            'summary': summary,
            'reason': '',
            'booking': booking,
            'member': member,
            'created_at': event_at,
            'link_url': reverse(url_name, kwargs={
                'booking_id': booking.pk,
            }),
            'link_label': 'Ver seguimiento',
            'incident_id': incident.pk,
        })

    updates.sort(
        key=lambda update: update['created_at'],
        reverse=True,
    )
    return updates[:limit]