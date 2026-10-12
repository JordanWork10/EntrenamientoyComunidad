from django.urls import path

from . import views


app_name = 'activities'


urlpatterns = [
    path(
        '',
        views.activities_home,
        name='home',
    ),

    path(
        'mis-actividades/',
        views.my_activities,
        name='my_activities',
    ),

    path(
        'comunitarias/crear/',
        views.create_community_activity,
        name='create_community',
    ),

    path(
        'profesionales/crear/',
        views.create_professional_activity,
        name='create_professional',
    ),

    path(
        '<int:activity_id>/editar/',
        views.edit_community_activity,
        name='edit_community',
    ),

    path(
        '<int:activity_id>/editar-profesional/',
        views.edit_professional_activity,
        name='edit_professional',
    ),

    path(
        '<int:activity_id>/publicar/',
        views.publish_community_activity,
        name='publish_community',
    ),

    path(
        '<int:activity_id>/publicar-profesional/',
        views.publish_professional_activity,
        name='publish_professional',
    ),

    path(
        '<int:activity_id>/unirme/',
        views.join_activity,
        name='join',
    ),

    path(
        '<int:activity_id>/salir/',
        views.leave_activity,
        name='leave',
    ),

    path(
        '<int:activity_id>/',
        views.activity_detail,
        name='detail',
    ),
]
