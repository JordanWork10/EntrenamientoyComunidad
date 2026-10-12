from django.urls import path

from . import home_views


app_name = 'core'


urlpatterns = [
    path(
        '',
        home_views.home,
        name='home',
    ),

    path(
        'explorar/',
        home_views.explore,
        name='explore',
    ),
]
