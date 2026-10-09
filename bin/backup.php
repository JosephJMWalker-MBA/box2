<?php
declare(strict_types=1);
require dirname(__DIR__).'/app/bootstrap.php';
if (PHP_SAPI!=='cli') exit(1);
$directory=config()['storage_path'].'/backups';
if (!is_dir($directory)) mkdir($directory,0700,true);
$path=$directory.'/box2-'.gmdate('Ymd-His').'-'.bin2hex(random_bytes(3)).'.sqlite';
db()->exec('VACUUM INTO '.db()->quote($path));chmod($path,0600);
echo "Consistent SQLite backup created: ".$path."\n";
