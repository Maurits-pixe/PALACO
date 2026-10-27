FROM node:24.22.1-bookworm-slim
WORKDIR /app
COPY --chown=node:node services/bastion-demo/ services/bastion-demo/
COPY --chown=node:node modules/aether-preview/src/envelope.js modules/aether-preview/src/envelope.js
RUN mkdir /data && chown node:node /data
USER node
ENV BASTION_HOST=0.0.0.0
ENV BASTION_DATABASE=/data/tasks.sqlite
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s CMD node -e "fetch('http://127.0.0.1:3000/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"
CMD ["node", "services/bastion-demo/server.mjs"]
