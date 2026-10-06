from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User
from django_celery_results.models import TaskResult
from .models import DailySummary

class CustomUserAdmin(UserAdmin):
    model = User

    # Ensure 'role' field appears in the user edit form with a dropdown
    fieldsets = UserAdmin.fieldsets + (
        ('Custom Fields', {'fields': ('role',)}),
    )

    # Ensure 'role' field appears in the user creation form with a dropdown
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Custom Fields', {'fields': ('role',)}),
    )

    list_display = ('username', 'email', 'role', 'is_staff', 'is_active')  # Display roles in the user list
    list_filter = ('role', 'is_staff', 'is_active')  # Add a filter in admin panel
    search_fields = ('username', 'email', 'role')

    # No save_model override: UserAdmin's forms already hash the password
    # (the add form via set_password, the change-password view via its own
    # form). Calling set_password again on obj.password re-hashed that hash,
    # so a user created here could not log in with the password they were
    # given until they reset it.

admin.site.register(User, CustomUserAdmin)

# @admin.register(TaskResult)
class TaskResultAdmin(admin.ModelAdmin):
    list_display = ('task_id', 'task_name', 'status', 'date_done', 'result')
    list_filter = ('status', 'date_done')
    search_fields = ('task_id', 'task_name')

@admin.register(DailySummary)
class DailySummaryAdmin(admin.ModelAdmin):
    list_display = ('date', 'process', 'pending', 'approved')
    list_filter = ('date', 'process')
