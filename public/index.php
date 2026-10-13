<?php
declare(strict_types=1);

ini_set('display_errors','0');error_reporting(E_ALL);
require_once dirname(__DIR__).'/app/bootstrap.php';
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
header('X-Frame-Options: DENY');
header('Permissions-Policy: camera=(), microphone=(), geolocation=()');
header("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; media-src 'self'; frame-src https://player.twitch.tv; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");
header('Cache-Control: no-store');
$route='/';$title='Come Tell It Here First';$error='';$notice='';$result=null;$editorialLink='';
try {
    $basePath=rtrim(parse_url(config()['base_url'],PHP_URL_PATH)??'','/');
    $path=parse_url($_SERVER['REQUEST_URI'],PHP_URL_PATH);
    $route=$basePath!==''&&str_starts_with($path,$basePath.'/')?substr($path,strlen($basePath)):$path;
    if ($route==='/index.php') $route='/';
    if ($_SERVER['REQUEST_METHOD']==='POST' && !forms_ready()) throw new RuntimeException('Secure forms are unavailable on this connection.',403);
    start_session();
    if ($route==='/api/slots' || $route==='/booking-options') {
        $choice='public';
        if ($route==='/booking-options') {
            if ($_SERVER['REQUEST_METHOD']!=='POST') throw new RuntimeException('Method not allowed.',403);
            verify_csrf($_POST);throttle('booking_options',60);
            $choice=field($_POST,'capture_choice',20,true);
        }
        $night=filter_var(($route==='/booking-options'?$_POST:$_GET)['night']??null,FILTER_VALIDATE_INT);
        if (!$night) throw new InvalidArgumentException('Choose a show.');
        header('Content-Type: application/json');
        $show=query('SELECT id,show_date,status FROM show_nights WHERE id=?',[$night])->fetch();
        if (!$show) throw new InvalidArgumentException('Show not found.');
        echo json_encode(['slots'=>booking_options($night,$choice),'night'=>$show,'bookings_enabled'=>bookings_open()],JSON_THROW_ON_ERROR);exit;
    }
    if (preg_match('#^/media/([a-f0-9]{32})$#D',$route,$match)) serve_arrival($match[1]);
    if (str_starts_with($route,'/admin') && $route!=='/admin/login' && !admin()) {
        header('Location: '.url('/admin/login'));exit;
    }
    if ($_SERVER['REQUEST_METHOD']==='POST') {
        verify_csrf($_POST);
        if (in_array($route,['/book','/writers'],true)) {
            throttle($route,8);if (field($_POST,'website',100)!=='') throw new InvalidArgumentException('Unable to submit this form.');
        }
        if ($route==='/book') {if (!flag($_POST,'refresh_options')) $result=create_booking($_POST);}
        elseif ($route==='/writers') $result=submit_writer($_POST);
        elseif ($route==='/respond') $result=['booking'=>apply_booking_link($_POST)];
        elseif ($route==='/release') {throttle('editorial_release',12);$result=apply_editorial_release($_POST);}
        elseif ($route==='/withdraw') {throttle('withdraw',12);withdraw_writer(field($_POST,'token',64,true));$notice='Future production permission withdrawn. Previously published copies are not recalled.';}
        elseif ($route==='/admin/login') {
            throttle('login',5,900);
            $password=$_POST['password']??'';
            if (!is_string($password) || $password==='' || strlen($password)>72) throw new InvalidArgumentException('Unable to sign in. Check your password.');
            if (config()['admin_password_hash']==='' || !password_verify($password,config()['admin_password_hash'])) {
                throw new InvalidArgumentException('Unable to sign in. Check your password.');
            }
            session_regenerate_id(true);$_SESSION['admin']=true;$_SESSION['last_active']=time();$_SESSION['csrf']=bin2hex(random_bytes(32));
            header('Location: '.url('/admin'));exit;
        } elseif ($route==='/admin/logout') {
            require_admin();$_SESSION=[];session_regenerate_id(true);session_destroy();header('Location: '.url('/'));exit;
        } elseif ($route==='/admin/action') {
            require_admin();$action=field($_POST,'action',30,true);
            $id=field($_POST,'booking_id',24);
            $night=filter_var($_POST['night_id']??null,FILTER_VALIDATE_INT);
            if ($action==='recording') set_recording_mode((int)$night,field($_POST,'mode',20,true),$_POST);
            elseif ($action==='capture') set_capture_state((int)$night,$_POST);
            elseif ($action==='room_clear') clear_private_room((int)$night,$_POST);
            elseif ($action==='override') override_night((int)$night,$_POST);
            elseif ($action==='slot') {
                $slot=filter_var($_POST['slot_id']??null,FILTER_VALIDATE_INT);
                $visibility=field($_POST,'visibility',10,true);
                if (!in_array($visibility,['public','hold','private'],true)) throw new InvalidArgumentException('Invalid slot visibility.');
                transaction(function () use ($slot,$visibility): void {
                    if (query('SELECT 1 FROM booking_allocations WHERE slot_id=? AND active=1',[$slot])->fetchColumn()) throw new InvalidArgumentException('Cancel this booking before changing any of its reserved slots.');
                    query('UPDATE slots SET visibility=? WHERE id=?',[$visibility,$slot]);audit('slot_'.$visibility,(string)$slot);
                });
            } elseif ($action==='sanitation') {
                $location=field($_POST,'location',10,true);
                if (!in_array($location,['mic','lobby','bathroom'],true)) throw new InvalidArgumentException('Invalid cleaning location.');
                query('INSERT INTO sanitation_checks(show_night_id,location,created_at) VALUES (?,?,?)',[$night,$location,utc()]);audit('sanitation_'.$location,(string)$night);
            } elseif ($action==='upload') upload_arrival($_FILES['video']??[],field($_POST,'transcript',10000,true));
            elseif ($action==='walk_in') {create_booking($_POST,true);}
            elseif ($action==='writer_production') {
                $writerId=field($_POST,'writer_id',24,true);
                query("UPDATE writer_submissions SET status='in_production' WHERE id=? AND status='submitted'",[$writerId]);audit('writer_production',$writerId);
            } else host_booking_action($id,$action,field($_POST,'host_note',1000),flag($_POST,'no_archive_confirmed')===1);
            $_SESSION['notice']='Host update saved.';
            header('Location: '.url('/admin'.($night?'?night='.$night:'')));exit;
        } elseif ($route==='/admin/editorial') {
            require_admin();$action=field($_POST,'action',30,true);$candidate=field($_POST,'candidate_id',24);
            if ($action==='create') create_editorial_candidate($_POST);
            elseif ($action==='release_link') $editorialLink=editorial_link($candidate,field($_POST,'role',10,true));
            elseif ($action==='review') review_editorial_candidate($candidate,field($_POST,'status',20,true));
            elseif ($action==='select') select_top5($candidate,(int)field($_POST,'position',1,true));
            elseif ($action==='unselect') unselect_top5($candidate);
            elseif ($action==='edited') edited_top5(field($_POST,'week_date',10,true),$_POST);
            elseif ($action==='post') record_top5_post(field($_POST,'week_date',10,true),field($_POST,'platform',20,true),field($_POST,'url',2048,true));
            else throw new InvalidArgumentException('Unknown editorial action.');
            if ($editorialLink==='') {$_SESSION['notice']='Editorial ledger updated; no media was rendered or posted.';header('Location: '.url('/admin/editorial'));exit;}
        } else throw new RuntimeException('Page not found.',404);
    }
    if ($route==='/release' && !$result) $result=['authorization'=>editorial_authorization($_GET),'link_fields'=>$_GET];
    if (!in_array($route,['/','/book','/rules','/arrive','/arrival','/writers','/terms','/privacy','/respond','/withdraw','/release','/admin','/admin/login','/admin/editorial'],true)) {
        throw new RuntimeException('Page not found.',404);
    }
} catch (Throwable $exception) {
    $expected=$exception instanceof InvalidArgumentException || in_array($exception->getCode(),[403,404,429,503],true);
    http_response_code($expected?($exception instanceof InvalidArgumentException?422:$exception->getCode()):500);
    $error=$expected?$exception->getMessage():'This request could not be completed. Please try again or contact the host.';
    if (!$expected) error_log('BOX2 internal error: '.get_class($exception).' at '.basename($exception->getFile()).':'.$exception->getLine());
    if (in_array($route,['/api/slots','/booking-options'],true)) {header('Content-Type: application/json');echo json_encode(['error'=>$error]);exit;}
    if (str_starts_with($route,'/admin/') && !in_array($route,['/admin/login','/admin/editorial'],true)) $route='/admin';
}
require dirname(__DIR__).'/app/views/layout.php';
