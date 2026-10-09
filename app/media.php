<?php
declare(strict_types=1);

function validate_upload(string $path,int $size,string $transcript): string
{
    if ($size<=0 || $size>25*1024*1024 || $size!==filesize($path)) throw new InvalidArgumentException('Walkthrough video limit is 25 MB.');
    if (trim($transcript)==='' || mb_strlen($transcript)>10000) throw new InvalidArgumentException('Provide a text walkthrough (maximum 10,000 characters).');
    $mime=(new finfo(FILEINFO_MIME_TYPE))->file($path);
    if (!in_array($mime,['video/mp4','video/webm'],true)) throw new InvalidArgumentException('Only verified MP4 or WebM video is accepted.');
    return $mime;
}

function upload_arrival(array $upload,string $transcript): void
{
    require_admin();
    if (($upload['error']??UPLOAD_ERR_NO_FILE)!==UPLOAD_ERR_OK || !is_uploaded_file($upload['tmp_name'])) {
        throw new InvalidArgumentException('Choose a video that uploaded successfully.');
    }
    $mime=validate_upload($upload['tmp_name'],(int)$upload['size'],$transcript);
    $id=bin2hex(random_bytes(16));
    $directory=config()['storage_path'].'/uploads';
    if (!is_dir($directory)) mkdir($directory,0700,true);
    $disk=$id.($mime==='video/mp4'?'.mp4':'.webm');
    if (!move_uploaded_file($upload['tmp_name'],$directory.'/'.$disk)) throw new RuntimeException('Upload could not be stored.');
    chmod($directory.'/'.$disk,0600);
    query('INSERT INTO media_assets(id,disk_name,mime,size,transcript,approved,created_at) VALUES (?,?,?,?,?,1,?)',
        [$id,$disk,$mime,(int)$upload['size'],$transcript,utc()]);
    audit('arrival_upload',$id);
}

function serve_arrival(string $id): never
{
    if (!config()['venue_public_enabled']) throw new RuntimeException('Media unavailable.',404);
    $asset=query("SELECT * FROM media_assets WHERE id=? AND approved=1 AND kind='arrival'",[$id])->fetch();
    if (!$asset) throw new RuntimeException('Media unavailable.',404);
    $path=config()['storage_path'].'/uploads/'.$asset['disk_name'];
    if (!is_file($path)) throw new RuntimeException('Media unavailable.',404);
    $size=filesize($path); $start=0; $end=$size-1;
    if (isset($_SERVER['HTTP_RANGE'])) {
        if (!preg_match('/^bytes=(\d+)-(\d*)$/D',$_SERVER['HTTP_RANGE'],$match)) {
            http_response_code(416); header('Content-Range: bytes */'.$size); exit;
        }
        $start=(int)$match[1]; $end=$match[2]===''?$end:(int)$match[2];
        if ($start>$end || $end>=$size) {http_response_code(416);header('Content-Range: bytes */'.$size);exit;}
        http_response_code(206);header("Content-Range: bytes {$start}-{$end}/{$size}");
    }
    header('Content-Type: '.$asset['mime']);header('Accept-Ranges: bytes');
    header('Content-Length: '.($end-$start+1));header('Cache-Control: private, max-age=0');
    $file=fopen($path,'rb');fseek($file,$start);
    for ($left=$end-$start+1;$left>0&&!feof($file);) {
        $part=fread($file,min(65536,$left));echo $part;$left-=strlen($part);
    }
    fclose($file);exit;
}
