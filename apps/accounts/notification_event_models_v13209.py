"""
V132.09A - Historial persistente de notificaciones.

Destino:
apps/accounts/notification_event_models_v13209.py

Este modelo conserva acontecimientos destinados a los usuarios.

IMPORTANTE:
- No reemplaza NotificationReadState.
- No modifica reservas, pagos, actividades ni incidencias.
- No genera notificaciones automáticamente.
- No almacena fichas clínicas ni antecedentes médicos.
- No permite enlaces externos en las notificaciones.
- Cada acontecimiento debe tener una clave estable.
"""

import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class NotificationEvent(models.Model):
    """
    Representa una notificación persistente.

    NotificationReadState continúa siendo responsable
    de registrar cuándo fue revisada por el usuario.

    El acontecimiento y su estado de lectura se mantienen
    separados para conservar compatibilidad con V128.
    """

    class Scope(models.TextChoices):

        MEMBER = (
            "member",
            "Miembro",
        )

        PROFESSIONAL = (
            "professional",
            "Profesional",
        )

    class Category(models.TextChoices):

        BOOKING = (
            "booking",
            "Reserva profesional",
        )

        SPACE = (
            "space",
            "Arriendo de espacio",
        )

        ACTIVITY = (
            "activity",
            "Actividad",
        )

        INCIDENT = (
            "incident",
            "Incidencia",
        )

        PAYMENT = (
            "payment",
            "Pago",
        )

        VIDEO = (
            "video",
            "Video profesional",
        )

        SYSTEM = (
            "system",
            "Plataforma",
        )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_events",
        verbose_name="Destinatario",
    )

    scope = models.CharField(
        max_length=20,
        choices=Scope.choices,
        verbose_name="Panel",
    )

    notification_key = models.CharField(
        max_length=255,
        verbose_name="Clave única de la notificación",
    )

    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        verbose_name="Categoría",
    )

    title = models.CharField(
        max_length=180,
        verbose_name="Título",
    )

    summary = models.CharField(
        max_length=600,
        blank=True,
        verbose_name="Resumen",
    )

    detail_url = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="Enlace interno",
    )

    occurred_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="Fecha del acontecimiento",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de registro",
    )

    class Meta:

        verbose_name = "Notificación persistente"
        verbose_name_plural = "Notificaciones persistentes"

        ordering = [
            "-occurred_at",
            "-id",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "recipient",
                    "scope",
                    "notification_key",
                ],
                name="unique_notification_event_v13209",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "recipient",
                    "scope",
                    "-occurred_at",
                ],
                name="notif_event_user_scope_dt",
            ),
        ]

    def clean(self):
        """
        Valida las claves y restringe los enlaces
        a rutas internas de la plataforma.
        """

        super().clean()

        errors = {}

        key = self.notification_key or ""

        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}",
            key,
        ):
            errors["notification_key"] = (
                "La clave de notificación no es válida."
            )

        detail_url = self.detail_url or ""

        if detail_url:

            invalid_url = (
                not detail_url.startswith("/")
                or detail_url.startswith("//")
                or "\\" in detail_url
                or any(
                    ord(character) < 32
                    for character in detail_url
                )
            )

            if invalid_url:
                errors["detail_url"] = (
                    "Solo se permiten enlaces internos."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):

        return (
            f"{self.recipient_id} | "
            f"{self.scope} | "
            f"{self.notification_key}"
        )