-- Somente testes: banco descartável vazio, sem cadastro automático no ingestor.
BEGIN;
INSERT INTO andares (id, nome) VALUES (1, 'andar teste');
INSERT INTO setores (id, andar_id, nome) VALUES (1, 1, 'setor teste');
INSERT INTO zonas (id, setor_id, nome) VALUES (1, 1, 'zona teste');
INSERT INTO leitores (id, reader_id, fabricante, modelo, identificador_serial)
VALUES (1, 'reader-01', 'simulador', 'teste', 'serial-independente');
INSERT INTO antenas (id, leitor_id, porta_numero, zona_associada_id, funcao)
VALUES (1, 1, 1, 1, 'indefinido');
COMMIT;
