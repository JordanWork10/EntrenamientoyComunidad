"""
V132.07B - Pruebas de seguridad del administrador de limpiezas.

Destino:
apps/professionals/tests_professional_video_cleanup_admin_v13207.py

Comprueba:

- Registro del modelo en Django Admin.
- Acceso exclusivo para superusuarios.
- Restricción para usuarios normales y personal administrativo.
- Campos de solo lectura.
- Prohibición de crear, editar o eliminar registros.
- Ausencia de acciones administrativas masivas.

No realiza operaciones sobre Supabase Storage.
"""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .models import ProfessionalVideoStorageCleanup


class ProfessionalVideoCleanupAdminTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.superuser = User.objects.create_superuser(
            username="cleanup_superuser_v13207",
            email="cleanup_superuser@example.test",
            password="test-password",
        )

        cls.staff_user = User.objects.create_user(
            username="cleanup_staff_v13207",
            email="cleanup_staff@example.test",
            password="test-password",
        )

        cls.staff_user.is_staff = True
        cls.staff_user.save(update_fields=["is_staff"])

        cls.member = User.objects.create_user(
            username="cleanup_member_v13207",
            email="cleanup_member@example.test",
            password="test-password",
        )

    def setUp(self):
        self.factory = RequestFactory()

        self.model_admin = admin.site._registry[
            ProfessionalVideoStorageCleanup
        ]

        self.superuser_request = self.factory.get("/")
        self.superuser_request.user = self.superuser

        self.staff_request = self.factory.get("/")
        self.staff_request.user = self.staff_user

        self.member_request = self.factory.get("/")
        self.member_request.user = self.member

        self.admin_url = reverse(
            "admin:professionals_"
            "professionalvideostoragecleanup_changelist"
        )

    def test_cleanup_model_is_registered(self):
        """
        El modelo debe estar registrado en Django Admin.
        """

        self.assertTrue(
            admin.site.is_registered(
                ProfessionalVideoStorageCleanup
            )
        )

    def test_list_display_uses_correct_profile_field(self):
        """
        Comprueba que se utiliza el nombre real del campo.
        """

        self.assertIn(
            "professional_profile_id_snapshot",
            self.model_admin.list_display,
        )

        self.assertIn(
            "status",
            self.model_admin.list_display,
        )

        self.assertIn(
            "attempts",
            self.model_admin.list_display,
        )

    def test_superuser_can_view_module(self):
        """
        Un superusuario puede consultar el módulo.
        """

        self.assertTrue(
            self.model_admin.has_module_permission(
                self.superuser_request
            )
        )

        self.assertTrue(
            self.model_admin.has_view_permission(
                self.superuser_request
            )
        )

    def test_staff_without_superuser_cannot_view_module(self):
        """
        Ser miembro del personal no otorga acceso.
        """

        self.assertFalse(
            self.model_admin.has_module_permission(
                self.staff_request
            )
        )

        self.assertFalse(
            self.model_admin.has_view_permission(
                self.staff_request
            )
        )

    def test_regular_member_cannot_view_module(self):
        """
        Los miembros normales no pueden consultar registros.
        """

        self.assertFalse(
            self.model_admin.has_module_permission(
                self.member_request
            )
        )

        self.assertFalse(
            self.model_admin.has_view_permission(
                self.member_request
            )
        )

    def test_superuser_cannot_modify_cleanup_records(self):
        """
        Incluso un superusuario debe tener acceso de solo lectura.
        """

        self.assertFalse(
            self.model_admin.has_add_permission(
                self.superuser_request
            )
        )

        self.assertFalse(
            self.model_admin.has_change_permission(
                self.superuser_request
            )
        )

        self.assertFalse(
            self.model_admin.has_delete_permission(
                self.superuser_request
            )
        )

    def test_all_model_fields_are_readonly(self):
        """
        Ningún campo del modelo debe poder editarse.
        """

        readonly_fields = set(
            self.model_admin.get_readonly_fields(
                self.superuser_request
            )
        )

        model_fields = {
            field.name
            for field in
            ProfessionalVideoStorageCleanup._meta.concrete_fields
        }

        self.assertEqual(
            readonly_fields,
            model_fields,
        )

    def test_superuser_can_open_admin_listing(self):
        """
        La vista administrativa debe responder correctamente.
        """

        self.client.force_login(self.superuser)

        response = self.client.get(self.admin_url)

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_staff_cannot_open_admin_listing(self):
        """
        Un usuario staff sin privilegios de superusuario
        debe recibir acceso denegado.
        """

        self.client.force_login(self.staff_user)

        response = self.client.get(self.admin_url)

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_no_bulk_administrative_actions(self):
        """
        No deben existir acciones masivas de modificación
        o eliminación de registros.
        """

        actions = self.model_admin.get_actions(
            self.superuser_request
        )

        self.assertEqual(
            actions,
            {},
        )