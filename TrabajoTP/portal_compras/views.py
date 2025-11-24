from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
import json
import requests
from django.conf import settings
from django.contrib.auth import logout as auth_logout
from .keycloak_auth import keycloak_login_required

# Configuración Keycloak
KEYCLOAK_SERVER_URL = settings.KEYCLOAK_SERVER_URL
KEYCLOAK_REALM = settings.KEYCLOAK_REALM
KEYCLOAK_CLIENT_ID = settings.KEYCLOAK_CLIENT_ID

def index(request):
    """Página principal"""
    return render(request, 'portal_compras/index.html', {
        'user': request.user if request.user.is_authenticated else None
    })

def login_view(request):
    """Vista de login que muestra opciones de autenticación"""
    if request.user.is_authenticated:
        return redirect('index')
    
    return render(request, 'portal_compras/login.html', {
        'keycloak_enabled': True,
        'keycloak_url': f'{KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/auth'
    })

def registro_view(request):
    """Redirige a Keycloak para registro"""
    keycloak_registro_url = (
        f"{KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}/"
        f"protocol/openid-connect/registrations"
        f"?client_id={KEYCLOAK_CLIENT_ID}&response_type=code&scope=openid profile email&redirect_uri=http://localhost:8000/social-auth/complete/keycloak/"
    )
    return redirect(keycloak_registro_url)

def logout_view(request):
    """Cerrar sesión tanto en Django como en Keycloak"""
    # Guardar si es usuario de Keycloak antes de hacer logout
    is_keycloak_user = False
    if hasattr(request, 'user') and request.user.is_authenticated:
        social_auth = getattr(request.user, 'social_auth', None)
        if social_auth and social_auth.filter(provider='keycloak').exists():
            is_keycloak_user = True
    
    # Hacer logout de Django
    auth_logout(request)
    
    # Crear respuesta que limpie localStorage
    if is_keycloak_user:
        keycloak_logout_url = (
            f"{KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}/"
            f"protocol/openid-connect/logout"
        )
        response = redirect(keycloak_logout_url)
    else:
        response = redirect('index')
    
    # Agregar script para limpiar localStorage
    response['Location'] += '?clear_storage=true'
    
    return response

def shopcart_view(request):
    """Página del carrito - SOLO del usuario autenticado"""
    if not request.user.is_authenticated:
        return redirect('login')
    
    try:
        # ✅ CORREGIDO: Usar el método seguro
        carrito = get_user_cart(request.user)
        
        carrito_data = {
            'items': carrito.items,
            'total': carrito.calculate_total()
        }
        
    except Exception as e:
        print(f"❌ Error en shopcart_view: {e}")
        carrito_data = {'items': [], 'total': 0}
    
    # Calcular subtotales
    for item in carrito_data['items']:
        item['subtotal'] = item.get('quantity', 0) * item.get('product', {}).get('price', 0)
    
    return render(request, 'portal_compras/carrito.html', {
        'carrito': carrito_data,
        'user': request.user
    })

@keycloak_login_required
def api_obtener_carrito(request):
    """API protegida: Obtener carrito SOLO del usuario actual"""
    try:
        # ✅ CORREGIDO: Usar método seguro
        carrito = get_user_cart(request.user)
        
        carrito_data = {
            "items": carrito.items,
            "total": carrito.calculate_total(),
            "cantidad_items": len(carrito.items)
        }
        
        return JsonResponse({
            "status": "success",
            "cliente": KEYCLOAK_CLIENT_ID,
            "carrito": carrito_data
        })
        
    except Exception as e:
        return JsonResponse({
            "error": f"Error al obtener carrito: {str(e)}"
        }, status=500)

@keycloak_login_required
@keycloak_login_required
def api_agregar_al_carrito(request):
    """API protegida: Agregar producto al carrito CON token de usuario"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            producto_id = data.get('producto_id')
            cantidad = data.get('cantidad', 1)
            
            print(f"🎯 api_agregar_al_carrito - Usuario: {request.user.username}")
            
            if not producto_id:
                return JsonResponse({"error": "producto_id es requerido"}, status=400)
            
            # ✅ OBTENER TOKEN DEL USUARIO AUTENTICADO
            access_token = obtener_token_usuario(request)
            if not access_token:
                return JsonResponse({"error": "No se pudo obtener token de usuario"}, status=401)
            
            # Obtener carrito del usuario
            carrito = get_user_cart(request.user)
            
            # ✅ OBTENER INFORMACIÓN DEL PRODUCTO CON TOKEN DE USUARIO
            producto_info = obtener_info_producto_con_token(access_token, producto_id)
            
            # Buscar si el producto ya está en el carrito
            producto_existente = None
            for i, item in enumerate(carrito.items):
                if item.get('producto_id') == producto_id:
                    producto_existente = i
                    break
            
            if producto_existente is not None:
                # Actualizar cantidad
                carrito.items[producto_existente]['cantidad'] += cantidad
            else:
                # Agregar nuevo producto con información REAL
                carrito.items.append({
                    'producto_id': producto_id,
                    'cantidad': cantidad,
                    'producto': {
                        'id': producto_id,
                        'name': producto_info.get('nombre', f'Producto {producto_id}'),
                        'price': float(producto_info.get('precio', 0)),
                        'description': producto_info.get('descripcion', ''),
                        'imagen_url': producto_info.get('imagenes', [{}])[0].get('url', '') if producto_info.get('imagenes') else ''
                    }
                })
            
            carrito.save()
            carrito.calculate_total()
            
            return JsonResponse({
                "status": "success",
                "message": "Producto agregado al carrito",
                "usuario": request.user.username,
                "carrito_id": carrito.id
            })
            
        except Exception as e:
            print(f"💥 Error en api_agregar_al_carrito: {e}")
            return JsonResponse({
                "error": f"Error al agregar al carrito: {str(e)}"
            }, status=500)
    
    return JsonResponse({"error": "Método no permitido"}, status=405)
@keycloak_login_required
def api_limpiar_carrito(request):
    """API protegida: Vaciar carrito"""
    try:
        # ✅ CORREGIDO: Usar método seguro
        carrito = get_user_cart(request.user)
        carrito.items = []
        carrito.total = 0
        carrito.save()
        
        return JsonResponse({
            "status": "success",
            "message": "Carrito vaciado",
            "cliente": KEYCLOAK_CLIENT_ID
        })
        
    except Exception as e:
        return JsonResponse({
            "error": f"Error al limpiar carrito: {str(e)}"
        }, status=500)

def orders_view(request):
    """Vista para el historial de órdenes - SOLO del usuario autenticado"""
    orders_data = []
    
    if request.user.is_authenticated:
        try:
            from .models import Order, OrderItem
            # ✅ CORREGIDO: Filtrar explícitamente por usuario actual
            orders = Order.objects.filter(user=request.user).prefetch_related('items').order_by('-date')
            
            for order in orders:
                order_data = {
                    'id': order.id,
                    'date': order.date.isoformat(),
                    'status': order.status,
                    'total': float(order.total),
                    'delivery_address': order.delivery_address,
                    'payment_method': order.payment_method,
                    'items': []
                }
                
                for item in order.items.all():
                    order_data['items'].append({
                        'productId': item.productId,
                        'quantity': item.quantity,
                        'product': {
                            'id': item.productId,
                            'name': f'Producto {item.productId}',
                            'price': float(item.price)
                        }
                    })
                
                orders_data.append(order_data)
                
        except Exception as e:
            print(f"❌ Error en orders_view: {e}")
    
    return render(request, 'portal_compras/ordenes.html', {
        'orders': orders_data,
        'user': request.user if request.user.is_authenticated else None
    })

def obtener_info_producto(request, producto_id):
    """Obtener información real del producto usando token del USUARIO"""
    try:
        # ✅ CORREGIDO: Usar token del usuario autenticado
        social_auth = request.user.social_auth.get(provider='keycloak')
        access_token = social_auth.extra_data['access_token']
        
        # Llamar a la API de Stock para obtener el producto específico
        stock_url = f"http://stock_backend_api:8081/v1/productos/{producto_id}"
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        response = requests.get(stock_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Error obteniendo producto {producto_id}: {response.status_code}")
    
    except Exception as e:
        print(f"Error obteniendo info del producto {producto_id}: {e}")
    
    # Fallback si no se puede obtener la información
    return {
        'nombre': f'Producto {producto_id}',
        'precio': 0,
        'descripcion': 'Información no disponible'
    }
# =============================================================================
# API ENDPOINTS PROTEGIDOS CON KEYCLOAK - COMPRAS
# =============================================================================

@keycloak_login_required
def api_crear_orden_compra(request):
    """API protegida: Crear una nueva orden de compra"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Validar datos requeridos
            items = data.get('items', [])
            if not items:
                return JsonResponse({
                    "error": "La orden debe contener items"
                }, status=400)
            
            # Crear la orden en la base de datos
            from .models import Order, OrderItem
            
            orden = Order.objects.create(
                user=request.user,
                total=data.get('total', 0),
                delivery_address=data.get('delivery_address', ''),
                payment_method=data.get('payment_method', 'TARJETA'),
                status='PENDIENTE'
            )
            
            # Crear items de la orden
            for item in items:
                OrderItem.objects.create(
                    order=orden,
                    productId=item.get('producto_id'),
                    quantity=item.get('cantidad', 1),
                    price=item.get('precio', 0)
                )
            
            return JsonResponse({
                "status": "success",
                "orden_id": orden.id,
                "message": "Orden creada exitosamente",
                "cliente": KEYCLOAK_CLIENT_ID
            })
            
        except Exception as e:
            return JsonResponse({
                "error": f"Error al crear orden: {str(e)}"
            }, status=500)
    
    return JsonResponse({"error": "Método no permitido"}, status=405)

@keycloak_login_required
def api_obtener_ordenes_usuario(request):
    """API protegida: Obtener órdenes SOLO del usuario actual"""
    try:
        from .models import Order
        
        # ✅ CORREGIDO: Filtrar explícitamente por usuario
        ordenes = Order.objects.filter(user=request.user).order_by('-date')
        
        ordenes_data = []
        for orden in ordenes:
            orden_data = {
                "id": orden.id,
                "fecha": orden.date.isoformat(),
                "total": float(orden.total),
                "estado": orden.status,
                "direccion_entrega": orden.delivery_address,
                "metodo_pago": orden.payment_method,
                "items": []
            }
            
            for item in orden.items.all():
                orden_data['items'].append({
                    "producto_id": item.productId,
                    "cantidad": item.quantity,
                    "precio": float(item.price),
                    "subtotal": float(item.quantity * item.price)
                })
            
            ordenes_data.append(orden_data)
        
        return JsonResponse({
            "status": "success",
            "cliente": KEYCLOAK_CLIENT_ID,
            "total_ordenes": len(ordenes_data),
            "ordenes": ordenes_data
        })
        
    except Exception as e:
        return JsonResponse({
            "error": f"Error al obtener órdenes: {str(e)}"
        }, status=500)
@keycloak_login_required
def api_obtener_carrito(request):
    """API protegida: Obtener carrito SOLO del usuario actual"""
    try:
        from .models import ShoppingCart
        
        # ✅ CORREGIDO: Usar get() en lugar de get_or_create() para evitar crear carritos vacíos
        carrito = ShoppingCart.objects.get(user=request.user)
        
        carrito_data = {
            "items": carrito.items,
            "total": carrito.calculate_total(),
            "cantidad_items": len(carrito.items)
        }
        
        return JsonResponse({
            "status": "success",
            "cliente": KEYCLOAK_CLIENT_ID,
            "carrito": carrito_data
        })
        
    except ShoppingCart.DoesNotExist:
        # Si no existe carrito, devolver vacío
        return JsonResponse({
            "status": "success",
            "cliente": KEYCLOAK_CLIENT_ID,
            "carrito": {
                "items": [],
                "total": 0,
                "cantidad_items": 0
            }
        })
    except Exception as e:
        return JsonResponse({
            "error": f"Error al obtener carrito: {str(e)}"
        }, status=500)

@keycloak_login_required
def api_agregar_al_carrito(request):
    """API protegida: Agregar producto al carrito SOLO del usuario actual"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            producto_id = data.get('producto_id')
            cantidad = data.get('cantidad', 1)
            
            if not producto_id:
                return JsonResponse({"error": "producto_id es requerido"}, status=400)
            
            # ✅ CORREGIDO: Usar método seguro
            carrito = get_user_cart(request.user)
            
            # ✅ CORREGIDO: Obtener información del producto con token de USUARIO
            producto_info = obtener_info_producto(request, producto_id)
            
            # Buscar si el producto ya está en el carrito
            producto_existente = None
            for i, item in enumerate(carrito.items):
                if item.get('producto_id') == producto_id:
                    producto_existente = i
                    break
            
            if producto_existente is not None:
                # Actualizar cantidad
                carrito.items[producto_existente]['cantidad'] += cantidad
            else:
                # Agregar nuevo producto con información REAL
                carrito.items.append({
                    'producto_id': producto_id,
                    'cantidad': cantidad,
                    'producto': {
                        'id': producto_id,
                        'name': producto_info.get('nombre', f'Producto {producto_id}'),
                        'price': float(producto_info.get('precio', 0)),
                        'description': producto_info.get('descripcion', ''),
                        'imagen_url': producto_info.get('imagenes', [{}])[0].get('url', '') if producto_info.get('imagenes') else ''
                    }
                })
            
            carrito.save()
            carrito.calculate_total()  # Recalcular total
            
            return JsonResponse({
                "status": "success",
                "message": "Producto agregado al carrito",
                "cliente": KEYCLOAK_CLIENT_ID,
                "usuario": request.user.username  # ✅ Para debug
            })
            
        except Exception as e:
            return JsonResponse({
                "error": f"Error al agregar al carrito: {str(e)}"
            }, status=500)
    
    return JsonResponse({"error": "Método no permitido"}, status=405)
@keycloak_login_required
def api_limpiar_carrito(request):
    """API protegida: Vaciar carrito"""
    try:
        from .models import ShoppingCart
        
        carrito, created = ShoppingCart.objects.get_or_create(user=request.user)
        carrito.items = []
        carrito.save()
        
        return JsonResponse({
            "status": "success",
            "message": "Carrito vaciado",
            "cliente": KEYCLOAK_CLIENT_ID
        })
        
    except Exception as e:
        return JsonResponse({
            "error": f"Error al limpiar carrito: {str(e)}"
        }, status=500)

def test_keycloak(request):
    """Test para verificar que Keycloak funciona"""
    try:
        from keycloak import KeycloakOpenID
        
        keycloak_openid = KeycloakOpenID(
            server_url=KEYCLOAK_SERVER_URL,
            client_id=KEYCLOAK_CLIENT_ID,
            realm_name=KEYCLOAK_REALM,
            client_secret_key=settings.KEYCLOAK_CLIENT_SECRET,
        )
        
        token = keycloak_openid.token(grant_type="client_credentials")
        return JsonResponse({
            "status": "success", 
            "message": "Keycloak integrado correctamente",
            "client_id": KEYCLOAK_CLIENT_ID,
            "token_obtenido": True
        })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)})

# Vista para perfil de usuario
@login_required
def profile_view(request):
    """Vista del perfil de usuario"""
    user = request.user
    profile_data = {
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'date_joined': user.date_joined,
    }
    
    is_keycloak_user = False
    if hasattr(user, 'social_auth'):
        social_auth = user.social_auth.filter(provider='keycloak')
        if social_auth.exists():
            is_keycloak_user = True
    
    return render(request, 'portal_compras/profile.html', {
        'profile': profile_data,
        'is_keycloak_user': is_keycloak_user,
        'user': user
    })

def login_error_view(request):
    """Vista para mostrar errores de autenticación"""
    return render(request, 'portal_compras/login_error.html', {
        'user': request.user if request.user.is_authenticated else None
    })

# =============================================================================
# INTEGRACIÓN CON API EXTERNA DE STOCK
# =============================================================================

@keycloak_login_required
def productos_stock(request):
    """API protegida: Proxy para productos del equipo Stock"""
    try:
        response = requests.get("http://localhost:8081/v1/productos", timeout=10)
        
        if response.status_code == 200:
            return JsonResponse({
                "status": "success",
                "source": "stock-api",
                "client": KEYCLOAK_CLIENT_ID,
                "data": response.json()
            })
        else:
            return JsonResponse({
                "status": "error", 
                "message": f"Stock API responded with status {response.status_code}"
            }, status=response.status_code)
            
    except requests.exceptions.RequestException as e:
        return JsonResponse({
            "status": "error",
            "message": f"Error connecting to Stock API: {str(e)}"
        }, status=500)

@keycloak_login_required  
def producto_detalle(request, producto_id):
    """API protegida: Producto específico del Stock"""
    try:
        response = requests.get(f"http://localhost:8081/v1/productos/{producto_id}", timeout=10)
        
        if response.status_code == 200:
            return JsonResponse({
                "status": "success",
                "data": response.json()
            })
        else:
            return JsonResponse({
                "status": "error",
                "message": f"Producto {producto_id} no encontrado"
            }, status=404)
            
    except requests.exceptions.RequestException as e:
        return JsonResponse({
            "status": "error",
            "message": f"Error connecting to Stock API: {str(e)}"
        }, status=500)
        
def lista_productos(request):
    """Vista CORREGIDA - usa token del usuario autenticado"""
    productos = []
    query = request.GET.get('q', '')
    categoria = request.GET.get('categoria', '')

    # Si no está autenticado, mostrar productos sin token
    if not request.user.is_authenticated:
        return render(request, 'portal_compras/productos.html', {
            'productos': [],
            'categorias': [],
            'user': None
        })

    try:
        # ✅ CORREGIDO: Obtener token del USUARIO autenticado, no client credentials
        social_auth = request.user.social_auth.get(provider='keycloak')
        access_token = social_auth.extra_data['access_token']
        
        print(f"🔄 Usando token de usuario: {request.user.username}")
        
        # ✅ CORREGIDO: Usar 'stock_backend_api' desde dentro de Docker con token de usuario
        stock_url = "http://stock_backend_api:8081/v1/productos"
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        print(f"🔄 Llamando a Stock API con token de usuario...")
        response = requests.get(stock_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            productos_api = response.json()
            print(f"✅ {len(productos_api)} productos obtenidos del Stock con token de usuario")
            
            # Transformar productos
            for producto in productos_api:
                categoria_principal = 'General'
                if producto.get('categorias') and len(producto['categorias']) > 0:
                    categoria_principal = producto['categorias'][0].get('nombre', 'General')
                
                imagen_principal = None
                if producto.get('imagenes') and len(producto['imagenes']) > 0:
                    for img in producto['imagenes']:
                        if img.get('esPrincipal'):
                            imagen_principal = img.get('url')
                            break
                    if not imagen_principal:
                        imagen_principal = producto['imagenes'][0].get('url')
                
                productos.append({
                    'id': producto.get('id'),
                    'name': producto.get('nombre'),
                    'description': producto.get('descripcion'), 
                    'price': float(producto.get('precio', 0)),
                    'stock': producto.get('stockDisponible', 0),
                    'category': categoria_principal,
                    'imagen_url': imagen_principal,
                    'ubicacion_ciudad': producto.get('ubicacion', {}).get('ciudad', ''),
                    'ubicacion_provincia': producto.get('ubicacion', {}).get('provincia', ''),
                })
        
        else:
            print(f"❌ Error Stock API: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"💥 Error general: {e}")
        import traceback
        traceback.print_exc()
    
    # Aplicar filtros
    if query:
        productos = [p for p in productos if query.lower() in p.get('name', '').lower()]
    
    if categoria:
        productos = [p for p in productos if p.get('category', '').lower() == categoria.lower()]
    
    # Categorías para filtros
    categorias = sorted(list(set([p.get('category', '') for p in productos if p.get('category')])))
    
    print(f"📦 Enviando {len(productos)} productos al template para usuario {request.user.username}")
    
    return render(request, 'portal_compras/productos.html', {
        'productos': productos,
        'categorias': categorias,
        'query': query,
        'categoria_seleccionada': categoria,
        'user': request.user
    })
def get_productos_prueba(mensaje_error=""):
    """Productos de prueba si falla la API"""
    return [{
        'id': 999,
        'name': f'Modo Prueba - {mensaje_error}',
        'description': 'No se pudo conectar al servicio Stock. Revisa que el client_secret de grupo-05 sea correcto.',
        'price': 0.00,
        'stock': 0,
        'category': 'General',
        'imagen_url': 'https://via.placeholder.com/300x200/ff9900/ffffff?text=Modo+Prueba',
        'ubicacion_ciudad': 'Resistencia',
        'ubicacion_provincia': 'Chaco'
    }]
from django.shortcuts import get_object_or_404

def get_user_cart(user):
    """✅ Método seguro para obtener o crear el carrito del usuario"""
    from .models import ShoppingCart
    try:
        return ShoppingCart.objects.get(user=user)
    except ShoppingCart.DoesNotExist:
        # Si no existe, crear uno nuevo
        return ShoppingCart.objects.create(user=user, items=[], total=0)

def obtener_token_usuario(request):
    """Obtener el token de acceso del usuario autenticado"""
    if not request.user.is_authenticated:
        return None
    
    try:
        # Obtener el token de Social Auth
        social_auth = request.user.social_auth.get(provider='keycloak')
        access_token = social_auth.extra_data.get('access_token')
        
        if access_token:
            print(f"✅ Token obtenido para usuario: {request.user.username}")
            return access_token
        else:
            print(f"❌ Usuario {request.user.username} no tiene token en social_auth")
            return None
            
    except Exception as e:
        print(f"❌ Error obteniendo token de usuario {request.user.username}: {e}")
        return None