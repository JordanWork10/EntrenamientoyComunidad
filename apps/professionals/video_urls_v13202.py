"""Destino: apps/professionals/video_urls_v13202.py

Se incorpora con include() desde el urlpatterns EXISTENTE de professionals.
No declarar app_name aquí: hereda professionals del archivo padre.
"""

from django.urls import path

from . import video_views_v13202


urlpatterns = [
    path('', video_views_v13202.portfolio_manager, name='portfolio_manager'),
    path('revision/', video_views_v13202.portfolio_review_queue, name='portfolio_review_queue'),
    path('revision/<uuid:public_id>/decidir/', video_views_v13202.portfolio_review_decide, name='portfolio_review_decide'),
    path('<uuid:public_id>/eliminar/', video_views_v13202.portfolio_delete, name='portfolio_delete'),
    path('<uuid:public_id>/archivo/', video_views_v13202.portfolio_stream, name='portfolio_stream'),
]
