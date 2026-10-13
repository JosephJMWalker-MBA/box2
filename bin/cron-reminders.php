<?php
declare(strict_types=1);
require dirname(__DIR__).'/app/bootstrap.php';
if (PHP_SAPI!=='cli') exit(1);
echo json_encode(process_reminders(),JSON_THROW_ON_ERROR)."\n";
