from social_core.backends.keycloak import KeycloakOAuth2
import jwt
import requests

class CustomKeycloakOAuth2(KeycloakOAuth2):
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ✅ DEFINIR USERINFO_URL desde settings
        from django.conf import settings
        self.USERINFO_URL = settings.SOCIAL_AUTH_KEYCLOAK_USERINFO_URL
    
    def get_user_id(self, details, response):
        """✅ EXTRAER el 'sub' del token de acceso directamente"""
        try:
            # Obtener el token de acceso de la respuesta
            access_token = response.get('access_token')
            if access_token:
                # Decodificar el token para obtener el sub
                decoded = jwt.decode(access_token, options={"verify_signature": False})
                user_id = decoded.get('sub')
                print(f"🔐 get_user_id - sub del token: {user_id}")
                return user_id
        except Exception as e:
            print(f"❌ Error extrayendo sub del token: {e}")
        
        # Fallback: usar el sub de la respuesta si está disponible
        user_id = response.get('sub')
        print(f"🔐 get_user_id - sub de response: {user_id}")
        return user_id
    
    def get_user_details(self, response):
        """Obtener detalles del usuario - USANDO ID_TOKEN"""
        print(f"🔐 get_user_details - INICIANDO...")
        print(f"🔐 get_user_details - Response keys: {list(response.keys())}")
        
        # ✅ EXTRAER DATOS DEL ID_TOKEN que SÍ funciona
        id_token = response.get('id_token')
        if id_token:
            try:
                decoded_id = jwt.decode(id_token, options={"verify_signature": False})
                print(f"🔐 get_user_details - ID_TOKEN DECODIFICADO:")
                print(f"  preferred_username: {decoded_id.get('preferred_username')}")
                print(f"  given_name: {decoded_id.get('given_name')}")
                print(f"  family_name: {decoded_id.get('family_name')}")
                print(f"  email: {decoded_id.get('email')}")
                
                # Usar datos del id_token
                username = decoded_id.get('preferred_username', '')
                email = decoded_id.get('email', '')
                first_name = decoded_id.get('given_name', '')
                last_name = decoded_id.get('family_name', '')
                
            except Exception as e:
                print(f"❌ Error decodificando id_token: {e}")
                username = response.get('preferred_username', '')
                email = response.get('email', '')
                first_name = response.get('given_name', '')
                last_name = response.get('family_name', '')
        else:
            # Fallback a response normal
            username = response.get('preferred_username', '')
            email = response.get('email', '')
            first_name = response.get('given_name', '')
            last_name = response.get('family_name', '')
        
        if not username:
            username = response.get('sub', '')
        
        user_details = {
            'username': username,
            'email': email,
            'first_name': first_name,
            'last_name': last_name,
        }
        
        print(f"🔐 get_user_details - User details final: {user_details}")
        return user_details
    
    def user_data(self, access_token, *args, **kwargs):
        """Obtener datos del usuario - SOLO SI USERINFO_URL ESTÁ DISPONIBLE"""
        try:
            print(f"🔐 user_data - INICIANDO...")
            
            if hasattr(self, 'USERINFO_URL') and self.USERINFO_URL:
                print(f"🔐 user_data - Userinfo URL: {self.USERINFO_URL}")
                
                # Llamar al endpoint de userinfo
                response = self.request(
                    self.USERINFO_URL,
                    headers={'Authorization': f'Bearer {access_token}'}
                )
                
                print(f"🔐 user_data - Status Code: {response.status_code}")
                
                if response.status_code == 200:
                    user_data = response.json()
                    print(f"🔐 user_data - USERINFO RESPONSE: {user_data}")
                    user_data['access_token'] = access_token
                    return user_data
                else:
                    print(f"❌ user_data - Error userinfo: {response.status_code}")
            else:
                print("⚠️ user_data - USERINFO_URL no disponible")
                
        except Exception as e:
            print(f"❌ Error en user_data: {e}")
        
        # Si userinfo falla, devolver solo el token
        return {'access_token': access_token}

    def extra_data(self, user, uid, response, details=None, *args, **kwargs):
        """✅ FORZAR que TODOS los campos se guarden en extra_data"""
        data = super().extra_data(user, uid, response, details, *args, **kwargs)
        
        print(f"🔐 extra_data - INICIANDO...")
        
        # ✅ EXTRAER DATOS DEL ID_TOKEN para guardar en extra_data
        id_token = response.get('id_token')
        if id_token:
            try:
                decoded_id = jwt.decode(id_token, options={"verify_signature": False})
                print(f"🔐 extra_data - ID_TOKEN para extra_data:")
                
                # Guardar todos los campos importantes
                important_fields = {
                    'email': decoded_id.get('email'),
                    'given_name': decoded_id.get('given_name'),
                    'family_name': decoded_id.get('family_name'),
                    'preferred_username': decoded_id.get('preferred_username'),
                    'sub': decoded_id.get('sub')
                }
                
                for field, value in important_fields.items():
                    if value:
                        data[field] = value
                        print(f"🔐 extra_data - {field} del id_token: {value}")
                        
            except Exception as e:
                print(f"❌ Error extrayendo datos del id_token: {e}")
        
        print(f"🔐 extra_data - DATA final: {data}")
        return data

    # Mantén tus métodos existentes para la public key
    def public_key(self):
        public_key_value = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAvRNUYBCIBoBLKvj9dFjHHhR3YCY93OkBQ/okdg5F1kRrXZOlHWoP1DLh4IYadr0DtlBWqQJWgzHr/Symo86F5f4mLqdiGX7zXoH6jvig8EX1fOF+tkXK4GeyEpPaU3FBHEoptSZGiHSQJhd2q1bPVwyh9LcsWdUktRUEhyJaa+kTQxLtt816dny9JpRgDt1JfZYNs9i66iqfBfGoF88Mf7z7QKKP9D9JlYHvnzKcqtSqUcW0T2QO195gBGV0hL/df1owBVC0CI1pKoddUZNAiEvUDk2OE7ERdcBy5YY04vwoP6EVrGJi3bYKrtkYZdmxj7obfgUhHSvuu2BwxpN1yQIDAQAB"
        if public_key_value:
            return f"-----BEGIN PUBLIC KEY-----\n{public_key_value}\n-----END PUBLIC KEY-----"
        return None
    
    def get_key(self, secret=None):
        return None
    
    def decode_token(self, token, verify=True):
        try:
            decoded = jwt.decode(
                token, 
                options={"verify_signature": False, "verify_aud": False}
            )
            return decoded
        except Exception as e:
            print(f"❌ Error decodificando token: {e}")
            return {}