"""
V129 - Prueba aislada del bloqueo con correo y RUT.

Ejecutar desde la carpeta del proyecto con:
    python manage.py shell < prueba_axes_correo_rut_v129.py

Crea un usuario temporal con RUT ficticio y lo elimina en `finally`.
No usa usuarios reales ni modifica sus contrasenas.
"""

from uuid import uuid4

from axes.models import AccessAttempt, AccessFailureLog
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()
unique = uuid4().hex[:12]
email = f"prueba-axes-{unique}@example.invalid"
username = f"v129_axes_test_{unique}"
rut = "99999999-9"  # RUT sintético para pruebas; dígito verificador correcto.
password = "ClaveTemporalDePrueba!2026"

if User.objects.filter(rut__iexact=rut).exists():
    print("PRUEBA NO INICIADA: el RUT ficticio ya figura registrado.")
else:
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        rut=rut,
        first_name="Prueba",
        last_name="Seguridad",
        is_active=True,
    )
    try:
        client = Client(
            HTTP_HOST="127.0.0.1",
            REMOTE_ADDR="127.0.0.1",
            raise_request_exception=False,
        )
        wrong_password = "ClaveIncorrectaDePrueba!2026"
        attempts = [
            (email, wrong_password),        # Fallo 1: correo.
            (rut, wrong_password),          # Fallo 2: RUT con guion.
            ("999999999", wrong_password), # Fallo 3: RUT sin guion.
            (email.upper(), wrong_password),# Fallo 4: correo con mayúsculas.
            (rut, wrong_password),          # Fallo 5: debe bloquear (429).
            (email, password),              # Clave correcta: debe seguir bloqueado.
        ]
        statuses = []
        for identifier, candidate_password in attempts:
            response = client.post(
                "/cuenta/login/",
                {"identifier": identifier, "password": candidate_password},
            )
            statuses.append(response.status_code)

        failures = list(
            AccessAttempt.objects.filter(username=username)
            .values_list("failures_since_start", flat=True)
        )
        active_session = bool(client.session.get("_auth_user_id"))

        print("ESTADOS HTTP:", statuses)
        print("REGISTROS AXES:", AccessAttempt.objects.filter(username=username).count())
        print("FALLOS REGISTRADOS:", failures)
        print("SESION INICIADA:", active_session)
        passed = statuses == [200, 200, 200, 200, 429, 429] and not active_session
        print("PROTECCION CORREO + RUT:", "CORRECTA" if passed else "REVISAR")
    finally:
        AccessAttempt.objects.filter(username=username).delete()
        AccessFailureLog.objects.filter(username=username).delete()
        user.delete()
        print("USUARIO Y REGISTROS TEMPORALES: LIMPIADOS")
