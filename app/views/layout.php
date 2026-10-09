<?php
declare(strict_types=1);
$titles=['/book'=>'Book a set','/rules'=>'Performer orientation','/arrive'=>'Arrive prepared',
    '/writers'=>'Writer submissions','/terms'=>'Terms + recording permissions','/privacy'=>'Privacy',
    '/admin'=>'Host desk','/admin/login'=>'Host sign in','/respond'=>'Your booking','/withdraw'=>'Writer permissions'];
$title=$titles[$route]??$title;
$canonical=url($route);
if ($route==='/book') {
    $sharedNight=false;
    if (isset($_GET['show']) && is_string($_GET['show']) && preg_match('/^\d{4}-\d{2}-\d{2}$/D',$_GET['show'])) {
        $sharedNight=query('SELECT show_date,status FROM show_nights WHERE show_date=?',[$_GET['show']])->fetch();
    } elseif (isset($_GET['night']) && is_string($_GET['night']) && ctype_digit($_GET['night'])) {
        $sharedNight=query('SELECT show_date,status FROM show_nights WHERE id=?',[(int)$_GET['night']])->fetch();
    }
    if ($sharedNight) {
        $canonical.='?show='.$sharedNight['show_date'];
        $title='Show evening '.$sharedNight['show_date'].' · '.$sharedNight['status'];
    }
}
?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="theme-color" content="#f04d22"><title><?= e($title) ?> | BOX2</title>
    <meta name="description" content="Canton, Ohio comedy development stage. Everybody starts somewhere. Start here.">
    <link rel="canonical" href="<?= e($canonical) ?>">
    <?php if (in_array($route,['/','/book','/rules','/arrive'],true)): ?>
    <meta property="og:type" content="website"><meta property="og:title" content="BOX2 — <?= e($title) ?>">
    <meta property="og:description" content="Original comedy. Five minutes of work. Come tell it here first.">
    <meta property="og:url" content="<?= e($canonical) ?>"><meta property="og:image" content="<?= e(url('/assets/share.png')) ?>">
    <meta name="twitter:card" content="summary_large_image">
    <?php else: ?><meta name="robots" content="noindex, nofollow"><?php endif; ?>
    <link rel="stylesheet" href="<?= e(url('/assets/site.css?v='.BOX2_VERSION)) ?>">
    <script src="<?= e(url('/assets/site.js?v='.BOX2_VERSION)) ?>" defer></script>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="site-header">
    <a class="brand" href="<?= e(url()) ?>" aria-label="BOX2 home">BOX2<span>CANTON, OH</span></a>
    <nav aria-label="Main navigation">
        <a href="<?= e(url('/book')) ?>">Book</a><a href="<?= e(url('/rules')) ?>">Orientation</a>
        <a href="<?= e(url('/arrive')) ?>">Arrival</a><a href="<?= e(url('/writers')) ?>">Writers</a>
    </nav>
</header>
<main id="main">
<?php if ($error): ?><p class="message error" role="alert"><?= e($error) ?></p><?php endif; ?>
<?php if ($notice): ?><p class="message" role="status"><?= e($notice) ?></p><?php endif; ?>
<?php
$view=match($route) {
    '/'=>'home', '/book','/respond'=>'book', '/rules','/arrive'=>'orientation',
    '/writers','/withdraw'=>'writers', '/admin','/admin/login'=>'admin', '/terms','/privacy'=>'policy', default=>'home'
};
try {require __DIR__.'/'.$view.'.php';}
catch (Throwable $exception) {http_response_code(503);echo '<p class="message error">This page is unavailable until local setup is complete.</p>';error_log('BOX2 view error: '.get_class($exception));}
?>
</main>
<footer><strong>BOX2 — Come Tell It Here First.</strong><nav aria-label="Footer">
    <a href="<?= e(url('/terms')) ?>">Terms</a><a href="<?= e(url('/privacy')) ?>">Privacy</a>
    <a href="<?= e(url('/admin')) ?>">Host desk</a></nav>
    <small>Version <?= e(BOX2_VERSION) ?> · Powered by <a href="https://yurrmom.com/shop">YurrMom.com/shop</a></small>
</footer>
</body></html>
