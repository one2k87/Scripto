<?php
/* === Scripto URL 정리 (2026-11-19, 보드 s-url-plan 승인) ===
 * 통합한 글 → 남길 글로 301, 정리한 글 → 410(영구 삭제 신호). 원문은 임시글로 보관.
 * 붙일 곳: 외모 → 테마 파일 편집기 → functions.php 맨 끝(기존 Scripto 블록 아래).
 */
add_action('template_redirect', function () {
    $path = trim(parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH), '/');
    $map301 = array(
        'mobile-id-bank-confusion-2026' => 'mobile-id-card-issuance-senior-guide',
        'hospital-pharmacy-kiosk-payment-guide' => 'senior-hospital-kiosk-registration',
        'mvno-data-usage-check-after-switch' => '2026-september-senior-data-usage-check',
        'senior-mobile-drivers-license-guide' => 'mobile-id-card-issuance-senior-guide',
        'mobile-id-screen-instead-of-photo' => 'mobile-id-card-issuance-senior-guide',
        'galaxy-a25-screenshot-button-method' => 'galaxy-s24-screen-capture-button-guide',
        'galaxy-s24-call-error-fix' => 'galaxy-s24-phone-call-error-network-reset',
        'galaxy-s24-wifi-senior-settings' => 'galaxy-s24-wifi-disconnect-network-reset',
        'senior-smartphone-ringtones-notifications' => 'galaxy-s24-ringtone-notification-volume-settings',
        'government24-certificate-free-easy-steps' => 'gov24-resident-registration-copy-senior',
        'government24-mobile-id-senior-digital-guide' => 'mobile-id-card-issuance-senior-guide',
        'senior-smartphone-video-call-seamless-free' => 'senior-kakaotalk-videocall-troubleshooting',
        'hospital-kiosk-receipt-issue' => 'senior-hospital-kiosk-registration',
        'senior-hospital-mobile-registration-tips' => 'senior-hospital-kiosk-registration',
        'galaxy-a15-battery-drain-senior-fix' => 'galaxy-a25-battery-drain-replacement-comparison',
        'galaxy-a15-screenshot-guide-senior' => 'galaxy-a15-screen-capture-senior-guide',
    );
    $gone = array(
        'remote-control-app-scam-response',
        'parents-voice-phishing-remote-app-citizen-conan-guide',
        'kakao-talk-phishing-prevention-senior',
        'lower-senior-phone-bill-2026',
        'senior-digital-suspicious-payment-sms-202610',
        'senior-parents-overseas-travel-currency-exchange-mobile-guide',
        'senior-digital-fraud-prevention-202610',
        'senior-digital-education-2026-october',
        'alt-phone-customer-service-number-202610',
        'senior-phone-data-saving-2026-10',
        'senior-smartphone-spam-block-report-2026-10',
        'senior-phone-micro-payment-limit-check-reduce',
        '2026-10-senior-smartphone-airplane-mode-communication',
        'senior-digital-education-2026-september',
        'senior-telecom-saving-mvno-2026-09',
        'senior-digital-low-cost-unlimited-plan-202609',
        'senior-smartphone-unexpected-charges',
        'senior-digital-phone-payment-phishing-block',
        'senior-alttelphone-value-added-service-cancel',
        'senior-digital-mvno-portability-guide',
        'senior-phone-suspicious-link-prevention-2026-09',
        'boice-phishing-prevention-senior-2026-september',
        'senior-affordable-phone-plan-comparison-2026-09',
        'smishing-text-message-distinction-for-seniors-2026',
        'senior-digital-assistance-2026-09',
    );
    if (isset($map301[$path])) {
        wp_redirect(home_url('/' . $map301[$path] . '/'), 301, 'Scripto');
        exit;
    }
    if (in_array($path, $gone, true)) {
        status_header(410);
        nocache_headers();
        header('X-Robots-Tag: noindex');
        echo '<!doctype html><meta charset="utf-8"><title>삭제된 글</title><p style="font-family:sans-serif;padding:40px">이 글은 정리되어 더 이상 제공하지 않습니다. <a href="' . esc_url(home_url('/')) . '">원더랜드 홈으로</a></p>';
        exit;
    }
}, 1);
/* === Scripto URL 정리 끝 === */

/* === Scripto 아카이브 정리 (2026-11-19, s-url-plan) ===
 * 카테고리·태그 목록 페이지는 noindex,follow / 사이트맵에서 분류·작성자 제외 → 사이트맵은 글·페이지만.
 */
add_filter('rank_math/frontend/robots', function ($robots) {
    if (is_category() || is_tag() || is_date()) {
        $robots['index'] = 'noindex';
        $robots['follow'] = 'follow';
    }
    return $robots;
});
add_filter('wp_sitemaps_add_provider', function ($provider, $name) {
    return in_array($name, array('taxonomies', 'users'), true) ? false : $provider;
}, 10, 2);
/* === Scripto 아카이브 정리 끝 === */
