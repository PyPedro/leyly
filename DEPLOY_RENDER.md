# Deploy no Render

## Antes de publicar

1. Crie um banco PostgreSQL persistente no Render, de preferência na mesma região do serviço web, e copie a Internal Database URL. Esse passo é obrigatório: pedidos, clientes e estoque não devem usar SQLite.
2. Crie ou atualize o serviço usando o Blueprint deste repositório (`render.yaml`). O plano `starter` e o disco persistente de 1 GB têm custo no Render.
3. Preencha as variáveis marcadas como secretas durante a configuração do Blueprint:
   - `DATABASE_URL`: Internal Database URL do PostgreSQL. Se ela estiver ausente ou apontar para SQLite, a aplicação recusará iniciar para evitar perda de pedidos.
   - `ADMIN_EMAIL` e `ADMIN_PASSWORD`: credenciais fortes para o painel inicial.
   - `MERCADO_PAGO_ACCESS_TOKEN`: token de produção do Mercado Pago.
4. Confirme `SECRET_KEY` (gerada pelo Render), `UPLOAD_DIR=/var/data/uploads`, `CEP_ORIGEM=55750-000`, `PESO_PRODUTO_GRAMAS=400` e `WHATSAPP_LOJA=558199475717` nas variáveis do serviço. O disk deve estar montado em `/var/data` para conter a pasta de uploads.
5. Faça o deploy e abra a loja. Na primeira requisição, o sistema cria as tabelas e o administrador inicial usando as credenciais configuradas.

O administrador só é criado automaticamente se ainda não existir nenhum registro e as duas variáveis `ADMIN_EMAIL` e `ADMIN_PASSWORD` estiverem definidas. Defina-as antes do primeiro acesso; alterar as variáveis depois não troca a senha de uma conta já criada.

## Login com Google

Crie um cliente OAuth do tipo aplicativo Web no Google Cloud Console. Cadastre como URI de redirecionamento autorizada `https://<dominio-da-loja>/login/google/callback` (use o domínio público configurado no Render) e defina `GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET` nas variáveis do serviço. O botão “Continuar com Google” só aparece quando as duas variáveis estão configuradas. O primeiro login cria a conta; se já existir uma conta com o mesmo e-mail verificado, ela é vinculada ao Google.

## Importar estoque inicial

Depois de publicar o código, abra o Shell do serviço Web no Render e execute primeiro a validação:

```powershell
python -m scripts.importar_estoque
```

O comando confere as 38 referências com o catálogo existente e não grava dados. Referências existentes são atualizadas; produtos ausentes são planejados para criação. Referências ambíguas interrompem a carga. Produtos novos ficam sem preço e sem imagem própria até que os dados sejam completados; aparecem como “Preço pendente no estoque” e não podem ser adicionados ao pedido. Cadastre os preços pelo estoque do admin antes de vender esses itens. Após conferir a lista de correspondências/criações, execute uma única vez:

```powershell
python -m scripts.importar_estoque --apply
```

A carga atualiza cores, tamanhos e quantidades, preserva imagens e preços de produtos existentes, cria os ausentes sem preço e sem imagem, e registra sua execução para impedir reaplicação acidental.

## Persistência e pagamentos

O PostgreSQL guarda produtos, clientes e pedidos. As imagens enviadas pelo painel são gravadas em `/var/data/uploads`, dentro do disk persistente montado em `/var/data`. Mantenha `UPLOAD_DIR` dentro do `mountPath` do disk; sem um disk montado em `/var/data` ou em um diretório pai de uploads, os arquivos ficam no sistema efêmero do serviço. Os arquivos estáticos incluídos no repositório continuam sendo servidos normalmente.

O frete exibido é uma estimativa interna por região e faixa de peso, usando o CEP de origem e o peso unitário configurados. Não é uma cotação oficial das transportadoras; para cobrar o valor exato, conecte uma API de frete com as credenciais da loja. Tokens Mercado Pago `TEST-` abrem o checkout sandbox e precisam de uma conta compradora de teste. Para receber pagamentos reais, configure o token de produção `APP_USR-` em `MERCADO_PAGO_ACCESS_TOKEN`; o sistema então usa o checkout de produção. `WHATSAPP_LOJA` deve conter o número da loja com código do país, apenas dígitos (`558199475717`).

Não use o SQLite local como banco de produção: o sistema de arquivos do serviço web é efêmero e não é compartilhado entre instâncias.