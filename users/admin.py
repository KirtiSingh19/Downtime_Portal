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

    def save_model(self, request, obj, form, change):
        if change:  # Editing an existing user
            if 'password' in form.changed_data:
                obj.set_password(obj.password)
        else:  # Creating a new user
            obj.set_password(obj.password)
        super().save_model(request, obj, form, change)

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
