from django.urls import path
from django.contrib.auth.decorators import login_required
from . import views
from django.shortcuts import redirect
from .views import profile_view
from django.contrib.auth import views as auth_views

urlpatterns = [
    # Authentication
    path('login/', views.user_login, name='user_login'),
    path('logout/', views.user_logout, name='user_logout'),

    # Regular User Routes
    path('home/', login_required(views.home), name='home'),

    # L1 User Routes (Approvers)
    path('approve/', login_required(views.approve_files), name='approve_files'),

    # L2 User Routes (Second-stage approvers, push to HRMS)
    path('approve-l2/', login_required(views.approve_files_l2), name='approve_files_l2'),

    # Optional: Redirect '/' to 'home' if logged in, otherwise to 'login'
    path('', lambda request: redirect('home') if request.user.is_authenticated else redirect('user_login'), name='index'),

    # Preview a file's contents in the browser, no download
    path('file/<int:file_id>/view/', login_required(views.view_file), name='view_file'),

    path('profile/', profile_view, name='profile'),
    
    path('password_reset/', auth_views.PasswordResetView.as_view(template_name='users/password_reset.html'), name='password_reset'),
    path('password_reset_done/', auth_views.PasswordResetDoneView.as_view(template_name='users/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='users/password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='users/password_reset_complete.html'), name='password_reset_complete'),

]
