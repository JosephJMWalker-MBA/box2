<?php
declare(strict_types=1);
// PHP development server only. Production uses public/ as the document root.
require_once dirname(__DIR__).'/app/bootstrap.php';
$path=parse_url($_SERVER['REQUEST_URI'],PHP_URL_PATH);
$basePath=rtrim(parse_url(config()['base_url'],PHP_URL_PATH)??'','/');
if ($basePath!=='' && str_starts_with($path,$basePath.'/')) $path=substr($path,strlen($basePath));
$file=realpath(__DIR__.$path);
if (str_starts_with($path,'/assets/') && $file && str_starts_with($file,__DIR__.'/assets/')
    && is_file($file) && in_array(pathinfo($file,PATHINFO_EXTENSION),['css','js','svg','png'],true)) {
    $types=['css'=>'text/css','js'=>'text/javascript','svg'=>'image/svg+xml','png'=>'image/png'];
    header('Content-Type: '.$types[pathinfo($file,PATHINFO_EXTENSION)]);
    header('X-Content-Type-Options: nosniff');readfile($file);return true;
}
require __DIR__.'/index.php';
