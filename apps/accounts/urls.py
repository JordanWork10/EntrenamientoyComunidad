from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views

from . import views
from . import notification_views


app_name = 'accounts'


urlpatterns = [

    # =====================================================
    # REGISTRO E INICIO DE SESIÓN
    # =====================================================

    path(
        'registro/',
        views.register,
        name='register'
    ),

    path(
        'login/',
        views.login_view,
        name='login'
    ),

    # =====================================================
    # V129 - RECUPERACIÓN DE CONTRASEÑA
    # =====================================================

    path(
        'contrasena/recuperar/',
        auth_views.PasswordResetView.as_view(
            template_name='accounts/password_reset_form.html',
            email_template_name='accounts/password_reset_email.txt',
            subject_template_name='accounts/password_reset_subject.txt',
            success_url=reverse_lazy(
                'accounts:password_reset_done'
            ),
        ),
        name='password_reset'
    ),

    path(
        'contrasena/recuperar/enviado/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='accounts/password_reset_done.html',
        ),
        name='password_reset_done'
    ),

    path(
        'contrasena/restablecer/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='accounts/password_reset_confirm.html',
            success_url=reverse_lazy(
                'accounts:password_reset_complete'
            ),
        ),
        name='password_reset_confirm'
    ),

    path(
        'contrasena/restablecer/completado/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='accounts/password_reset_complete.html',
        ),
        name='password_reset_complete'
    ),

    # =====================================================
    # PANEL Y ACTIVIDAD DEL MIEMBRO
    # =====================================================

    path(
        'panel/',
        views.dashboard,
        name='dashboard'
    ),

    path(
        'agenda/',
        views.member_agenda,
        name='member_agenda'
    ),

    path(
        'actividad/',
        views.activity_history,
        name='activity_history'
    ),

    # =====================================================
    # V128 - NOVEDADES DEL MIEMBRO
    # =====================================================

    path(
        'novedades/estado/',
        notification_views.member_notification_state,
        name='member_notification_state'
    ),

    path(
        'novedades/revisar/',
        notification_views.member_notification_mark_read,
        name='member_notification_mark_read'
    ),

    # =====================================================
    # CUENTA Y CONFIGURACIÓN
    # =====================================================

    path(
        'logout/',
        views.logout_view,
        name='logout'
    ),

    path(
        'comunas/',
        views.communes_by_region,
        name='communes_by_region'
    ),

    path(
        'configuracion/',
        views.profile_settings,
        name='profile_settings'
    ),
]