<?php
declare(strict_types=1);
require dirname(__DIR__).'/app/bootstrap.php';
if (PHP_SAPI!=='cli') exit(1);
migrate();
$date=$argv[1]??(new DateTimeImmutable('today',new DateTimeZone(BOX2_ZONE)))->format('Y-m-d');
foreach (generate_schedule($date) as $notice) echo $notice."\n";
echo "Migrations applied; 28-day schedule extended without overwriting host edits.\n";
