# Importaciones necesarias para Flask y funcionalidades del backend
from flask import Flask, request, jsonify
from flask_cors import CORS  # Para permitir requests desde la app Android
import os
import logging
from datetime import datetime, timedelta
import uuid
import json

# Importar configuración centralizada
from config import config

# Configuración de logging para monitoreo y debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Crear instancia de la aplicación Flask
app = Flask(__name__)

# Configurar la aplicación según el entorno
env = os.environ.get('FLASK_ENV', 'development')
app.config.from_object(config[env])

# Habilitar CORS para permitir requests desde diferentes orígenes (Android app)
CORS(app)

# Configuración adicional específica de la aplicación
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Límite de 16MB para uploads

# Diccionario en memoria para almacenar sesiones (en producción usar Redis/DB)
active_sessions = {}

# Diccionario para almacenar contenido pendiente de validación
pending_validations = {}

@app.route('/ping', methods=['GET'])
def ping():
    """
    Endpoint simple para verificar conectividad
    Responde inmediatamente para confirmar que el servidor está activo
    """
    logger.info("Ping request received")  # Log para monitoreo
    return jsonify({
        'status': 'ok',
        'message': 'Server is running',
        'timestamp': datetime.now().isoformat()
    }), 200

@app.route('/status', methods=['GET'])
def status():
    """
    Endpoint para verificar el estado de salud del sistema
    Proporciona información detallada sobre el estado de los servicios
    """
    logger.info("Status check requested")  # Log para monitoreo
    
    # Verificar estado de OpenAI API key
    openai_configured = bool(app.config.get('OPENAI_API_KEY'))
    
    # Contar sesiones activas
    active_session_count = len(active_sessions)
    
    # Contar validaciones pendientes
    pending_validation_count = len(pending_validations)
    
    # Crear respuesta de estado
    status_response = {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'environment': env,
        'services': {
            'openai': 'configured' if openai_configured else 'not_configured',
            'openai_model': app.config.get('OPENAI_MODEL', 'not_set'),
            'sessions': f'{active_session_count} active',
            'validations': f'{pending_validation_count} pending'
        },
        'config': {
            'max_content_length_mb': app.config.get('MAX_CONTENT_LENGTH', 0) // (1024 * 1024),
            'session_lifetime_hours': app.config.get('SESSION_LIFETIME', timedelta(hours=8)).total_seconds() // 3600,
            'rate_limit_per_minute': app.config.get('RATE_LIMIT_PER_MINUTE', 10)
        },
        'version': '1.0.0'
    }
    
    return jsonify(status_response), 200

@app.errorhandler(400)
def bad_request(error):
    """
    Manejador de errores para requests malformados (código 400)
    Proporciona respuesta JSON consistente para errores de cliente
    """
    logger.warning(f"Bad request: {error}")  # Log del error
    return jsonify({
        'error': 'Bad Request',
        'message': 'The request data is malformed or invalid',
        'timestamp': datetime.now().isoformat()
    }), 400

@app.errorhandler(404)
def not_found(error):
    """
    Manejador de errores para endpoints no encontrados (código 404)
    """
    logger.warning(f"Endpoint not found: {request.url}")  # Log del endpoint no encontrado
    return jsonify({
        'error': 'Not Found',
        'message': 'The requested endpoint does not exist',
        'timestamp': datetime.now().isoformat()
    }), 404

@app.errorhandler(500)
def internal_error(error):
    """
    Manejador de errores internos del servidor (código 500)
    Registra el error y proporciona respuesta genérica al usuario
    """
    logger.error(f"Internal server error: {error}")  # Log del error interno
    return jsonify({
        'error': 'Internal Server Error',
        'message': 'An unexpected error occurred. Please try again later.',
        'timestamp': datetime.now().isoformat()
    }), 500

@app.before_request
def log_request_info():
    """
    Middleware que se ejecuta antes de cada request
    Registra información de la solicitud para monitoreo
    """
    logger.info(f"Request: {request.method} {request.url} from {request.remote_addr}")

@app.after_request
def log_response_info(response):
    """
    Middleware que se ejecuta después de cada request
    Registra información de la respuesta para monitoreo
    """
    logger.info(f"Response: {response.status_code} for {request.method} {request.url}")
    return response

# Registrar blueprints de las rutas
try:
    from routes.chat_routes import bp_chat
    app.register_blueprint(bp_chat)
    logger.info("Chat routes registered successfully")
except ImportError as e:
    logger.warning(f"Could not import chat routes: {e}")

# Endpoint para crear sesiones
@app.route('/api/session/create', methods=['POST'])
def crear_sesion():
    """
    Crea una nueva sesión para el usuario
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Datos requeridos'}), 400
        
        user_id = data.get('user_id', f'user_{uuid.uuid4().hex[:8]}')
        device_type = data.get('device_type', 'unknown')
        app_version = data.get('app_version', '1.0.0')
        
        # Crear ID de sesión único
        session_id = str(uuid.uuid4())
        
        # Crear sesión con configuración del sistema
        session_data = {
            'id': session_id,
            'user_id': user_id,
            'device_type': device_type,
            'app_version': app_version,
            'created_at': datetime.now().isoformat(),
            'last_activity': datetime.now().isoformat(),
            'interaction_count': 0
        }
        
        # Almacenar sesión (en producción usar Redis/DB)
        active_sessions[session_id] = session_data
        
        logger.info(f"Nueva sesión creada: {session_id} para usuario {user_id}")
        
        return jsonify({
            'session_id': session_id,
            'status': 'created',
            'message': 'Sesión creada exitosamente',
            'timestamp': datetime.now().isoformat()
        }), 201
        
    except Exception as e:
        logger.error(f"Error creando sesión: {e}")
        return jsonify({
            'error': 'Error interno del servidor',
            'message': str(e)
        }), 500

# Registrar más rutas aquí según sea necesario
# from routes.training_routes import bp_training
# app.register_blueprint(bp_training)

if __name__ == '__main__':
    """
    Punto de entrada principal de la aplicación
    Configura el servidor para desarrollo o producción según el entorno
    """
    # Obtener configuración del entorno
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    
    logger.info(f"Starting OMAR Industrial AI Backend on {host}:{port}")
    logger.info(f"Debug mode: {debug_mode}")
    
    # Iniciar el servidor Flask
    app.run(host=host, port=port, debug=debug_mode)