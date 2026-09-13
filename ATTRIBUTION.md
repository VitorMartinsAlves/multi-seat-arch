# Attribution

Este projeto usa como referência o projeto público `garlett/multiseat`, branch `wlroots-0.20`:

- https://github.com/garlett/multiseat

Ideias reutilizadas/adaptadas:

- uso de `drm-lease-manager` para separar conectores da mesma GPU;
- um compositor wlroots/labwc por saída;
- associação de inputs a seats via systemd-logind;
- execução de sessões por `systemd-run`.

Mudanças principais nesta implementação:

- descoberta de input baseada em `udevadm`/`libinput` e syspath real;
- suporte a dispositivos I²C (ex.: touchpads ELAN), não apenas PS/2 e USB;
- configuração JSON estruturada;
- validação antes de aplicar;
- recuperação explícita para `seat0`;
- nenhuma alteração automática do target de boot;
- interface gráfica PyQt6;
- testes unitários e CI.

O projeto upstream é distribuído com licença GNU GPL; esta derivação permanece compatível com os termos da licença upstream.
