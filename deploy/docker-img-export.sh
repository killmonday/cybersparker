docker compose config --images
docker save -o docker_cybersparker_images.tar   cybersparker-deploy-worker  nginx:1.27-alpine  cybersparker-deploy-postgres  redis:7-alpine  cybersparker-deploy-web

#load
docker load -i docker_cybersparker_images.tar