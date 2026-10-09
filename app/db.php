<?php
declare(strict_types=1);

function db(bool $reset = false): PDO
{
    static $pdo;
    if ($reset) $pdo = null;
    if ($pdo === null) {
        $directory = config()['storage_path'];
        $public = realpath(config()['public_path']);
        if (!is_dir($directory)) mkdir($directory, 0700, true);
        $real = realpath($directory);
        if (!$public || !$real || $real === $public || str_starts_with($real, $public . DIRECTORY_SEPARATOR)) {
            throw new RuntimeException('Storage must be outside the public document root.');
        }
        $pdo = new PDO('sqlite:' . $real . '/box2.sqlite', null, null,
            [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC]);
        chmod($real . '/box2.sqlite', 0600);
        $pdo->exec('PRAGMA foreign_keys=ON');
        $pdo->exec('PRAGMA busy_timeout=5000');
    }
    return $pdo;
}

function query(string $sql, array $parameters = []): PDOStatement
{
    $statement = db()->prepare($sql);
    $statement->execute($parameters);
    return $statement;
}

function migrate(): void
{
    db()->exec('CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)');
    foreach (glob(dirname(__DIR__) . '/migrations/*.sql') as $file) {
        $version = basename($file);
        if (query('SELECT 1 FROM schema_migrations WHERE version=?', [$version])->fetchColumn()) continue;
        transaction(function () use ($file, $version): void {
            db()->exec(file_get_contents($file));
            query('INSERT INTO schema_migrations VALUES (?,?)', [$version, utc()]);
        });
    }
}

function transaction(callable $work): mixed
{
    $pdo = db();
    $pdo->beginTransaction();
    try {
        // Acquire SQLite's write lock before reading capacity. PDO tracks this transaction.
        $pdo->exec('UPDATE schema_migrations SET applied_at=applied_at WHERE 0');
        $result = $work();
        $pdo->commit();
        return $result;
    } catch (Throwable $exception) {
        if ($pdo->inTransaction()) $pdo->rollBack();
        throw $exception;
    }
}
