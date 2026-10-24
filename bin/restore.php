<?php
declare(strict_types=1);
require dirname(__DIR__).'/app/bootstrap.php';
if (PHP_SAPI!=='cli') exit(1);
if (config()['allow_bookings'] || !in_array('--confirm',$argv,true) || !isset($argv[1]) || $argv[1]==='--confirm') {
    fwrite(STDERR,"Disable bookings, stop ALL PHP workers/cron, back up current data, then run: php bin/restore.php /private/backup.sqlite --confirm\n");exit(1);
}
$source=realpath($argv[1]);
if (!$source) throw new RuntimeException('Backup not found.');
$backup=new PDO('sqlite:'.$source);
if ($backup->query('PRAGMA integrity_check')->fetchColumn()!=='ok'
    || !$backup->query("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'")->fetchColumn()) {
    throw new RuntimeException('Backup is not an intact BOX2 database.');
}
$backup=null;
$directory=realpath(config()['storage_path']);$public=realpath(config()['public_path']);
if (!$directory || $directory===$public || str_starts_with($directory,$public.'/')) throw new RuntimeException('Invalid private storage path.');
$target=$directory.'/box2.sqlite';
foreach (['-wal','-shm','-journal'] as $suffix) if (is_file($target.$suffix)) throw new RuntimeException('SQLite sidecars present: confirm all workers are stopped before restoring.');
$staged=$directory.'/restore-'.bin2hex(random_bytes(6)).'.sqlite';
if (!copy($source,$staged)) throw new RuntimeException('Backup could not be staged.');
chmod($staged,0600);
if (!rename($staged,$target)) throw new RuntimeException('Atomic restore failed.');
echo "Backup restored. Run migrate.php, verify integrity, and keep bookings disabled until the restore drill passes.\n";
