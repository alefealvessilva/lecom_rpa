# MIT License

Copyright (c) 2026 asclabs - Álefe Alves

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## Declaração de Governança e Conformidade com a LGPD

O **asclabs RPA Suite • Automatizador de Relatórios** foi projetado com observância integral à Lei Geral de Proteção de Dados Pessoais do Brasil (**Lei Federal nº 13.709/2018 - LGPD**), atendendo aos mais rigorosos padrões corporativos de segurança da informação e governança corporativa:

1. **Privacidade por Padrão e por Concepção (Privacy by Design & by Default):**
   - A solução é executada em sua totalidade de forma local (*on-premises*) na infraestrutura do usuário ou organização contratante.
   - O software **não** implementa qualquer serviço de telemetria, rastreamento, analytics ou transmissão remota de dados para terceiros ou para a asclabs.

2. **Minimização de Dados (Art. 6º, III):**
   - O banco de dados SQLite local (`rpa_dados.db`) persiste única e exclusivamente metadados operacionais: rótulos de endpoints de pesquisa, caminhos de destino no sistema de arquivos local e parâmetros de temporização.
   - O software **não armazena nem gerencia senhas, chaves de autenticação ou dados pessoais sensíveis**.

3. **Segurança de Acesso e Isolamento de Sessão (Art. 46):**
   - Toda a cadeia de autenticação (SSO, SAML e MFA) é delegada aos canais oficiais de navegador e aos provedores de identidade corporativos da própria organização operadora.
   - Os tokens e cookies temporários residem com exclusividade no diretório de perfil local do navegador parametrizado pelo operador do sistema.

4. **Direito do Titular e Retenção Controlada (Art. 16 e 18):**
   - O ciclo de vida dos arquivos gerados, bem como sua respectiva exclusão ou retenção, permanece sob total controle e custódia da organização operadora.
