from django.urls import path

from . import views


app_name = 'accounts'


urlpatterns = [
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