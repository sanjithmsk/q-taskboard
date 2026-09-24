from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User
from .serializers import UserSerializer, RegisterSerializer, LoginSerializer


def _token_for_user(user):
    return str(RefreshToken.for_user(user).access_token)


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'auth'

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': 'invalid input', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        email = serializer.validated_data['email']
        if User.objects.filter(email=email).exists():
            return Response({'error': 'email already registered'}, status=status.HTTP_400_BAD_REQUEST)
        user = User.objects.create_user(
            email=email,
            name=serializer.validated_data['name'],
            password=serializer.validated_data['password'],
        )
        return Response(
            {'user': UserSerializer(user).data, 'token': _token_for_user(user)},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'auth'

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'error': 'invalid input'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(email=serializer.validated_data['email'])
        except User.DoesNotExist:
            return Response({'error': 'invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        if not user.check_password(serializer.validated_data['password']):
            return Response({'error': 'invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        return Response({'user': UserSerializer(user).data, 'token': _token_for_user(user)})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({'user': UserSerializer(request.user).data})
