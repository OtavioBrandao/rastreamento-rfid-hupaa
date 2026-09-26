-- Executar APENAS em PostgreSQL local descartável após `alembic upgrade head`.
-- Dados sintéticos não representam equipamentos ou setores reais do HUPAA.
INSERT INTO tipos_equipamento (nome, nome_normalizado) VALUES ('Tipo sintético', 'tipo sintetico');
INSERT INTO andares (nome, nome_normalizado) VALUES ('Piso sintético', 'piso sintetico');
INSERT INTO setores (andar_id, nome, nome_normalizado)
SELECT id, 'Setor sintético', 'setor sintetico' FROM andares WHERE nome = 'Piso sintético';
INSERT INTO zonas (setor_id, nome, nome_normalizado, referencia_planta)
SELECT id, 'Zona sintética A', 'zona sintetica a', 'zona-1' FROM setores WHERE nome = 'Setor sintético';
INSERT INTO zonas (setor_id, nome, nome_normalizado, referencia_planta)
SELECT id, 'Zona sintética B', 'zona sintetica b', 'zona-2' FROM setores WHERE nome = 'Setor sintético';
INSERT INTO equipamentos (nome, tipo_id, identificador_interno,
                          identificador_interno_normalizado, status, ultima_zona_id,
                          ultima_deteccao_em)
SELECT 'Equipamento ' || lpad(gs::text, 5, '0'),
       (SELECT id FROM tipos_equipamento WHERE nome = 'Tipo sintético'),
       'MVP-' || gs, 'mvp' || gs,
       CASE WHEN gs % 10 = 0 THEN 'inativo' ELSE 'ativo' END,
       CASE WHEN gs % 7 = 0 THEN NULL ELSE
         (SELECT id FROM zonas WHERE nome = CASE WHEN gs % 2 = 0
           THEN 'Zona sintética A' ELSE 'Zona sintética B' END) END,
       CASE WHEN gs % 7 = 0 THEN NULL ELSE now() - (gs % 90) * interval '1 minute' END
FROM generate_series(1, 5000) AS gs;
INSERT INTO tags (epc)
SELECT 'E200' || lpad(to_hex(gs), 20, '0') FROM generate_series(1, 2500) AS gs;
INSERT INTO associacoes_tag_equipamento (tag_id, equipamento_id)
SELECT t.id, e.id FROM generate_series(1, 2500) AS gs
JOIN tags t ON t.epc = 'E200' || lpad(to_hex(gs), 20, '0')
JOIN equipamentos e ON e.identificador_interno = 'MVP-' || gs;
ANALYZE;

EXPLAIN (ANALYZE, BUFFERS)
SELECT e.id, e.nome, t.epc, z.nome
FROM equipamentos e
JOIN tipos_equipamento te ON te.id = e.tipo_id
LEFT JOIN associacoes_tag_equipamento a ON a.equipamento_id = e.id AND a.fim IS NULL
LEFT JOIN tags t ON t.id = a.tag_id
LEFT JOIN zonas z ON z.id = e.ultima_zona_id
WHERE e.tipo_id = (SELECT id FROM tipos_equipamento WHERE nome = 'Tipo sintético')
  AND e.ultima_zona_id = (SELECT id FROM zonas WHERE nome = 'Zona sintética A')
  AND e.ultima_deteccao_em < now() - interval '30 minutes'
ORDER BY e.nome, e.id LIMIT 20;

EXPLAIN (ANALYZE, BUFFERS)
SELECT e.id, e.nome, t.epc
FROM equipamentos e
JOIN tipos_equipamento te ON te.id = e.tipo_id
LEFT JOIN associacoes_tag_equipamento a ON a.equipamento_id = e.id AND a.fim IS NULL
LEFT JOIN tags t ON t.id = a.tag_id
WHERE t.epc = 'E20000000000000000000001'
ORDER BY e.nome, e.id LIMIT 20;
