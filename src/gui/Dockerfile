# ==============================================================================
# Dockerfile — GUI estática (HTML/CSS/JS vanilla, sin build step)
# nginx:alpine sirve los archivos tal cual — no hay compilación involucrada.
# ==============================================================================
FROM nginx:1.27-alpine

# Config mínima: servir estático + algunos headers de seguridad básicos.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copiar toda la GUI (html/css/js) al root servido por nginx.
COPY . /usr/share/nginx/html

# nginx:alpine ya corre su worker process como usuario "nginx" (no root) por defecto.
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]