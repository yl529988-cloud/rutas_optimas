// Simulación de API de huella digital
// En un entorno real, esto se integraría con la Web Authentication API

class FingerprintAuth {
    constructor() {
        this.isSupported = this.checkSupport();
    }

    checkSupport() {
        // En un entorno real, verificaríamos si el navegador soporta WebAuthn
        // return window.PublicKeyCredential !== undefined;
        
        // Por ahora, simulamos que está soportado
        return true;
    }

    async register(username) {
        if (!this.isSupported) {
            throw new Error('La autenticación por huella digital no es soportada por este navegador');
        }

        try {
            // Simulación de registro de huella
            // En un entorno real, usaríamos navigator.credentials.create()
            const fingerprintData = this.simulateFingerprintRegistration();
            
            return {
                success: true,
                fingerprintData: fingerprintData
            };
        } catch (error) {
            console.error('Error en registro de huella:', error);
            throw error;
        }
    }

    async authenticate(username) {
        if (!this.isSupported) {
            throw new Error('La autenticación por huella digital no es soportada por este navegador');
        }

        try {
            // Simulación de autenticación por huella
            // En un entorno real, usaríamos navigator.credentials.get()
            const fingerprintData = this.simulateFingerprintAuthentication();
            
            return {
                success: true,
                fingerprintData: fingerprintData
            };
        } catch (error) {
            console.error('Error en autenticación por huella:', error);
            throw error;
        }
    }

    simulateFingerprintRegistration() {
        // Simular datos de huella (en realidad serían datos criptográficos)
        return 'simulated_fingerprint_data_' + Date.now();
    }

    simulateFingerprintAuthentication() {
        // Simular datos de huella para autenticación
        return 'simulated_fingerprint_data_' + Date.now();
    }
}

// Inicializar cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', function() {
    const fingerprintAuth = new FingerprintAuth();
    
    // Hacer disponible globalmente para otros scripts
    window.fingerprintAuth = fingerprintAuth;
    
    // Configurar botones de huella si existen
    const registerFingerprintBtn = document.getElementById('register-fingerprint');
    const loginFingerprintBtn = document.getElementById('fingerprint-login');
    
    if (registerFingerprintBtn) {
        registerFingerprintBtn.addEventListener('click', async function() {
            const username = prompt('Por favor, ingresa tu usuario para registrar tu huella:');
            if (username) {
                try {
                    const result = await fingerprintAuth.register(username);
                    
                    // Enviar datos al servidor
                    const response = await fetch('/api/fingerprint/register', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            username: username,
                            fingerprint_data: result.fingerprintData
                        })
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        alert('Huella registrada correctamente');
                    } else {
                        alert('Error al registrar huella: ' + data.error);
                    }
                } catch (error) {
                    alert('Error: ' + error.message);
                }
            }
        });
    }
});