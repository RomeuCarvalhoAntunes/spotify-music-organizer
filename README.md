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

O fluxo de decisão manual permite selecionar um ou mais gêneros para uma faixa, álbum ou artista e transformar a decisão em regras reutilizáveis. Uma nova decisão substitui as regras anteriores do mesmo recurso.

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

POST   /classification/decisions
POST   /classifications/automatic
GET    /classifications/progress
POST   /classifications/rebuild
GET    /classification/review
GET    /tracks/{spotify_id}/genres
```

## Decisão manual

O endpoint POST /classification/decisions recebe um recurso e um ou mais gêneros. Uma nova decisão substitui as regras anteriores desse mesmo recurso:

```json
{
  "resource_type": "track",
  "spotify_id": "ID_DA_FAIXA",
  "genre_ids": [15, 19]
}
```

Os IDs dos gêneros podem ser consultados em GET /genres?include_disabled=false.

## Como executar localmente

Pré-requisitos:

- Docker e Docker Compose.
- Um aplicativo criado no painel de desenvolvedores do Spotify.
- O arquivo `.env` local já contém o Client ID fornecido e a URL http://127.0.0.1:8000/callback.
- No painel do Spotify, adicione exatamente essa URL como Redirect URI.

Subir a aplicação:

```bash
docker compose up --build -d
```

Verificar a saúde:

```bash
curl http://127.0.0.1:8000/health
```

Após autorizar em http://127.0.0.1:8000/login:

```bash
curl -X POST http://127.0.0.1:8000/imports
curl http://127.0.0.1:8000/classification/review
curl "http://127.0.0.1:8000/genres?include_disabled=false"
```

A classificação automática usa inicialmente as tags do Last.fm. Para habilitá-la, solicite uma API key no Last.fm e preencha LASTFM_API_KEY no .env. As faixas classificadas recebem evidência e confiança localmente; casos sem correspondência continuam na revisão manual.

A interface web está disponível em:

```text
http://127.0.0.1:8000/
```

Ela reúne status da aplicação e do Spotify, importação da biblioteca, fila de revisão, gêneros e decisões manuais.

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

1. Validar a decisão manual no Docker e criar um commit próprio.
2. Criar consultas locais para playlists, faixas e classificações.
3. Melhorar a fila de revisão com filtros, paginação e decisões em lote.
4. Adicionar fontes de classificação automática, mantendo a revisão humana para casos ambíguos.
5. Implementar a prévia de playlists por gênero sem alterar o Spotify.
6. Implementar sincronização explícita, com confirmação e proteção contra alterações acidentais.

## Princípios do projeto

- Dados importados e decisões do usuário permanecem locais por padrão.
- Nenhuma escrita no Spotify deve acontecer implicitamente.
- Regras manuais são reutilizáveis e têm precedência clara.
- Classificações devem ser explicáveis pela regra que as produziu.
- O banco local deve continuar útil mesmo quando o Spotify estiver offline.
