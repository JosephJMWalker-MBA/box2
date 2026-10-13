<?php
declare(strict_types=1);
require dirname(__DIR__).'/app/bootstrap.php';
$directory=sys_get_temp_dir().'/box2-ops-'.bin2hex(random_bytes(6));mkdir($directory,0700,true);
$settings=['storage_path'=>$directory,'environment'=>'local','secret'=>str_repeat('o',64),
    'allow_bookings'=>false,'venue_public_enabled'=>false]+config();
$path=$directory.'/config.php';file_put_contents($path,'<?php return '.var_export($settings,true).';');chmod($path,0600);
config($settings);migrate();$night=schedule_night('2030-10-11');
$environment=getenv();$environment['BOX2_CONFIG']=$path;
function command(array $arguments,array $environment): string {
    $process=proc_open(array_merge([PHP_BINARY],$arguments),[0=>['pipe','r'],1=>['pipe','w'],2=>['pipe','w']],$pipes,null,$environment);
    fclose($pipes[0]);$output=stream_get_contents($pipes[1]);$error=stream_get_contents($pipes[2]);fclose($pipes[1]);fclose($pipes[2]);
    if(proc_close($process)!==0) throw new RuntimeException($error);
    return $output;
}
command([dirname(__DIR__).'/bin/backup.php'],$environment);
$backup=glob($directory.'/backups/*.sqlite')[0]??null;
if(!$backup || (fileperms($backup)&0777)!==0600) throw new RuntimeException('Private backup missing.');
$copy=new PDO('sqlite:'.$backup);
if($copy->query('PRAGMA integrity_check')->fetchColumn()!=='ok') throw new RuntimeException('Backup integrity failed.');
$copy=null;
query('DELETE FROM slots');query('DELETE FROM show_nights');
// The restore runs only against this synthetic fixture and bookings are disabled.
command([dirname(__DIR__).'/bin/restore.php',$backup,'--confirm'],$environment);
db(true);
if((int)query('SELECT count(*) FROM slots')->fetchColumn()!==30) throw new RuntimeException('Restored slot count incorrect.');
if(query('PRAGMA integrity_check')->fetchColumn()!=='ok') throw new RuntimeException('Restored database integrity failed.');
echo "PASS consistent private backup, atomic synthetic restore, original slots preserved, integrity verified\n";
command([dirname(__DIR__).'/bin/retention.php'],$environment);
echo "PASS retention CLI runs without exposing private values\n";
$setupEnvironment=getenv();$setupEnvironment['BOX2_CONFIG']=$directory.'/setup-config.php';
$setupEnvironment['BOX2_STORAGE']=$directory.'/setup-data';
$setupEnvironment['BOX2_SETUP_PASSWORD']='synthetic-setup-password';
command([dirname(__DIR__).'/bin/setup.php','--local'],$setupEnvironment);
$setup=require $setupEnvironment['BOX2_CONFIG'];
if(!password_verify('synthetic-setup-password',$setup['admin_password_hash']) || strlen($setup['secret'])<32
    || $setup['allow_bookings']!==false || $setup['venue_public_enabled']!==false
    || (fileperms($setupEnvironment['BOX2_CONFIG'])&0777)!==0600) throw new RuntimeException('Setup security defaults failed.');
command([dirname(__DIR__).'/bin/migrate.php'],$setupEnvironment);
echo "PASS local setup hashes host password, generates private secret/config, leaves launch gates closed, and reruns migrations\n";
