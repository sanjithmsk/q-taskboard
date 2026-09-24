from rest_framework import serializers
from users.serializers import UserSerializer
from .models import Project, Membership, Task


class TaskSerializer(serializers.ModelSerializer):
    assignee = UserSerializer(read_only=True)
    assignee_id = serializers.SerializerMethodField()
    project_id = serializers.SerializerMethodField()
    created_by_id = serializers.SerializerMethodField()

    def get_assignee_id(self, obj):
        return str(obj.assignee_id) if obj.assignee_id else None

    def get_project_id(self, obj):
        return str(obj.project_id)

    def get_created_by_id(self, obj):
        return str(obj.created_by_id)

    class Meta:
        model = Task
        fields = [
            'id', 'project_id', 'title', 'description', 'status',
            'assignee_id', 'created_by_id', 'position', 'created_at', 'updated_at', 'assignee',
        ]


class ProjectWriteSerializer(serializers.Serializer):
    """Validates create/update input for projects. Use partial=True for PATCH."""
    name = serializers.CharField(max_length=120, allow_blank=False)
    description = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class TaskWriteSerializer(serializers.Serializer):
    """Validates create/update input for tasks. Use partial=True for PATCH.

    `assigneeId` is validated to be a current member of the task's project
    (passed via context), which also prevents cross-project assignment and the
    FK-violation 500 on a non-existent user id.
    """
    title = serializers.CharField(max_length=500, allow_blank=False)
    description = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    status = serializers.ChoiceField(choices=[c[0] for c in Task.STATUS_CHOICES], required=False)
    assigneeId = serializers.UUIDField(required=False, allow_null=True)

    def validate_assigneeId(self, value):
        if value is None:
            return None
        project_id = self.context.get('project_id')
        if not Membership.objects.filter(project_id=project_id, user_id=value).exists():
            raise serializers.ValidationError('assignee must be a member of this project')
        return value


class MembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ['id', 'role', 'user']


class ProjectDetailSerializer(serializers.ModelSerializer):
    owner = UserSerializer(read_only=True)
    owner_id = serializers.SerializerMethodField()
    memberships = MembershipSerializer(many=True, read_only=True)
    tasks = TaskSerializer(many=True, read_only=True)

    def get_owner_id(self, obj):
        return str(obj.owner_id)

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'owner_id', 'owner', 'memberships', 'tasks', 'created_at', 'updated_at']
