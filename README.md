# Spotify Music Organizer

Aplicação self-hosted para importar uma biblioteca do Spotify, organizar as músicas com gêneros definidos pelo usuário e, futuramente, gerar e sincronizar playlists de forma explícita e controlada.

## Objetivo

O projeto separa a leitura da biblioteca Spotify da organização local:

1. Autenticar o usuário no Spotify com OAuth e PKCE.
2. Importar playlists e faixas para um banco SQLite local.
3. Classificar as músicas com gêneros editáveis e regras reutilizáveis.
4. Revisar manualmente as músicas que ainda não possuem classificação.
5. Visualizar uma prévia das playlists que seriam criadas.
6. Futuramente, sincronizar alterações com o Spotify somente mediante ação explícita do usuário.

Até a etapa de sincronização, o sistema não deve escrever no Spotify.

## Estado atual

### Concluído

- Aplicação FastAPI executada com Docker Compose.
- OAuth Spotify com PKCE.
- Persistência local dos tokens e renovação automática.
- Leitura paginada do perfil, playlists e itens das playlists.
- Importação da biblioteca para SQLite.
- Deduplicação de faixas por `spotify_id`.
- Preservação das relações entre playlists e faixas.
- Endpoint `POST /imports` para atualizar o snapshot local.
- Estrutura inicial de gêneros editáveis em `src/default_genres.py`.

### Etapa atual

A etapa atual é a organização local por gêneros. O código já contém a base para:

- 27 gêneros iniciais com nome e descrição em português do Brasil;
- ativação e desativação de gêneros;
- regras por faixa, álbum e artista;
- precedência `faixa > álbum > artista`;
- classificações locais com origem e confiança;
- fila paginada de músicas sem classificação;
- endpoints REST para gêneros, regras, revisão e classificações.

O ponto pendente desta etapa é concluir e validar o fluxo de decisão manual: selecionar um ou mais gêneros para uma faixa, álbum ou artista e transformar a decisão em uma regra reutilizável.

## Endpoints principais

### Spotify e importação

```text
GET  /
GET  /health
GET  /login
GET  /callback
GET  /me
GET  /playlists
GET  /playlists/{playlist_id}/items
POST /imports
```

### Gêneros e classificação local

```text
GET    /genres
POST   /genres
GET    /genres/{genre_id}
PATCH  /genres/{genre_id}
DELETE /genres/{genre_id}

GET    /genre-rules
POST   /genre-rules
DELETE /genre-rules/{rule_id}

POST   /classifications/rebuild
GET    /classification/review
GET    /tracks/{spotify_id}/genres
```

## Como executar localmente

Pré-requisitos:

- Docker e Docker Compose.
- Um aplicativo criado no painel de desenvolvedores do Spotify.
- Um arquivo `.env` com as credenciais e a URL de callback configuradas.

Subir a aplicação:

```bash
docker compose up --build
```

Verificar a saúde:

```bash
curl http://127.0.0.1:8000/health
```

Abrir o fluxo de autenticação:

```text
http://127.0.0.1:8000/login
```

Executar os testes:

```bash
docker compose run --rm -v ./tests:/app/tests app python -m unittest discover -s tests
```

Validar a sintaxe:

```bash
docker compose run --rm -v ./tests:/app/tests app python -m compileall src tests
```

## Próximos passos

1. Finalizar o endpoint e os testes da decisão manual de classificação.
2. Validar a etapa completa no Docker e criar um commit próprio.
3. Criar consultas locais para playlists, faixas e classificações.
4. Melhorar a fila de revisão com filtros, paginação e decisões em lote.
5. Adicionar fontes de classificação automática, mantendo a revisão humana para casos ambíguos.
6. Implementar a prévia de playlists por gênero sem alterar o Spotify.
7. Implementar sincronização explícita, com confirmação e proteção contra alterações acidentais.

## Princípios do projeto

- Dados importados e decisões do usuário permanecem locais por padrão.
- Nenhuma escrita no Spotify deve acontecer implicitamente.
- Regras manuais são reutilizáveis e têm precedência clara.
- Classificações devem ser explicáveis pela regra que as produziu.
- O banco local deve continuar útil mesmo quando o Spotify estiver offline.
