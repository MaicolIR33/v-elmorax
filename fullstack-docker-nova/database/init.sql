CREATE DATABASE IF NOT EXISTS app_db;
USE app_db;

CREATE TABLE IF NOT EXISTS task (
  id INT NOT NULL AUTO_INCREMENT,
  title VARCHAR(255) NOT NULL,
  completed BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
);

INSERT INTO task (title)
SELECT 'realizar proyecto'
WHERE NOT EXISTS (SELECT 1 FROM task WHERE title = 'realizar proyecto');

INSERT INTO task (title)
SELECT 'hacer commits'
WHERE NOT EXISTS (SELECT 1 FROM task WHERE title = 'hacer commits');

INSERT INTO task (title)
SELECT 'configurar CD'
WHERE NOT EXISTS (SELECT 1 FROM task WHERE title = 'configurar CD');
