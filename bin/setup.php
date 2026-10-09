<?php
declare(strict_types=1);

require dirname(__DIR__).'/app/bootstrap.php';
if (PHP_SAPI!=='cli') exit(1);
$path=getenv('BOX2_CONFIG')?:dirname(__DIR__).'/config.local.php';
if (is_file($path)) {fwrite(STDERR,"Config exists; refusing to overwrite it.\n");exit(1);}
$password=getenv('BOX2_SETUP_PASSWORD');
if (!$password) {
    fwrite(STDOUT,"Choose host password (at least 12 characters; input hidden): ");
    system('stty -echo');
    try {$password=rtrim(fgets(STDIN),"\r\n");} finally {system('stty echo');fwrite(STDOUT,"\n");}
}
if (strlen($password)<12 || strlen($password)>72) {fwrite(STDERR,"Password must have 12-72 bytes.\n");exit(1);}
$settings=require dirname(__DIR__).'/config.example.php';
$settings['storage_path']=getenv('BOX2_STORAGE')?:$settings['storage_path'];
$settings['secret']=bin2hex(random_bytes(32));
$settings['admin_password_hash']=password_hash($password,PASSWORD_DEFAULT);
if (in_array('--local',$argv,true)) $settings['environment']='local';
umask(0077);
file_put_contents($path,"<?php\ndeclare(strict_types=1);\nreturn ".var_export($settings,true).";\n");
config($settings);migrate();
$notices=generate_schedule((new DateTimeImmutable('today',new DateTimeZone(BOX2_ZONE)))->format('Y-m-d'));
echo "Private configuration and SQLite initialized. Bookings remain disabled.\n";
foreach ($notices as $notice) echo $notice."\n";
