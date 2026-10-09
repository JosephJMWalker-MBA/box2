<?php
declare(strict_types=1);
require dirname(__DIR__).'/app/bootstrap.php';
$directory=sys_get_temp_dir().'/box2-browser-'.bin2hex(random_bytes(6));mkdir($directory,0700,true);
$settings=['storage_path'=>$directory,'base_url'=>$argv[1],'secret'=>bin2hex(random_bytes(32)),
    'environment'=>'local','admin_password_hash'=>password_hash('synthetic-host-password',PASSWORD_DEFAULT),
    'allow_bookings'=>true,'venue_public_enabled'=>true,'arrival_text'=>'Synthetic test directions. Not real parking instructions.']+config();
config($settings);migrate();$night=schedule_night('2030-10-11');
$path=$directory.'/config.php';file_put_contents($path,"<?php return ".var_export($settings,true).';');chmod($path,0600);
echo json_encode(['config'=>$path,'directory'=>$directory,'night'=>$night],JSON_THROW_ON_ERROR);
