"""
V132.06.5A - Rutas del portafolio audiovisual profesional.

Destino:
apps/professionals/video_urls_v13202.py

Mantiene las rutas existentes y utiliza eliminación recuperable
para los videos profesionales.

Los nombres de URL permanecen sin modificaciones.
"""

from django.urls import path

from . import (
    video_delete_views_v132065,
    video_edit_views_v13205,
    video_views_v13202,
)


urlpatterns = [
    path(
        '',
        video_views_v13202.portfolio_manager,
        name='portfolio_manager',
    ),

    path(
        'revision/',
        video_views_v13202.portfolio_review_queue,
        name='portfolio_review_queue',
    ),

    path(
        'revision/<uuid:public_id>/decidir/',
        video_views_v13202.portfolio_review_decide,
        name='portfolio_review_decide',
    ),

    path(
        '<uuid:public_id>/editar/',
        video_edit_views_v13205.portfolio_edit,
        name='portfolio_edit',
    ),

    path(
        '<uuid:public_id>/eliminar/',
        video_delete_views_v132065.portfolio_delete,
        name='portfolio_delete',
    ),

    path(
        '<uuid:public_id>/archivo/',
        video_views_v13202.portfolio_stream,
        name='portfolio_stream',
    ),
]