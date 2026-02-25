"""
Legal pages - Privacy Policy and Terms of Service
Required for Meta App approval and production deployment
"""

from flask import Blueprint, render_template_string

legal_bp = Blueprint("legal", __name__)

PRIVACY_POLICY_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Privacy Policy - Instagram Webhook Service</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6; 
            color: #333; 
            max-width: 800px; 
            margin: 0 auto; 
            padding: 40px 20px;
            background: #f5f5f5;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 { color: #1a1a1a; margin-bottom: 10px; font-size: 2em; }
        .last-updated { color: #666; margin-bottom: 30px; font-size: 0.9em; }
        h2 { color: #2c3e50; margin-top: 30px; margin-bottom: 15px; font-size: 1.3em; }
        p { margin-bottom: 15px; }
        ul { margin-left: 20px; margin-bottom: 15px; }
        li { margin-bottom: 8px; }
        .contact { 
            background: #f8f9fa; 
            padding: 20px; 
            border-radius: 6px; 
            margin-top: 30px;
        }
        @media (max-width: 600px) {
            body { padding: 20px 15px; }
            .container { padding: 25px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Privacy Policy</h1>
        <p class="last-updated">Last Updated: February 25, 2026</p>
        
        <h2>1. Introduction</h2>
        <p>Welcome to our Instagram Webhook Service ("we," "our," or "us"). We respect your privacy and are committed to protecting your personal data. This Privacy Policy explains how we collect, use, store, and protect your information when you use our service.</p>
        
        <h2>2. Information We Collect</h2>
        <p>We collect the following types of information:</p>
        <ul>
            <li><strong>Instagram Account Information:</strong> When you authenticate with Instagram, we receive your Instagram Business Account ID, username, and associated Facebook Page information.</li>
            <li><strong>Access Tokens:</strong> We store OAuth access tokens to interact with the Instagram API on your behalf.</li>
            <li><strong>Webhook Data:</strong> When someone comments on or mentions your Instagram posts, we receive the comment text, username, timestamp, and media ID.</li>
            <li><strong>Log Data:</strong> We maintain logs of webhook events for operational purposes.</li>
        </ul>
        
        <h2>3. How We Use Your Information</h2>
        <p>We use your information solely for:</p>
        <ul>
            <li>Processing and logging Instagram comments and mentions</li>
            <li>Authenticating with the Instagram API</li>
            <li>Providing webhook notifications for your specified events</li>
            <li>Maintaining service security and preventing abuse</li>
        </ul>
        
        <h2>4. Data Storage and Security</h2>
        <p><strong>Storage:</strong> Your data is stored securely in our SQLite database. Access tokens are encrypted at rest.</p>
        <p><strong>Retention:</strong> We retain your data only as long as necessary to provide the service. You can request deletion at any time by contacting us.</p>
        <p><strong>Security:</strong> We implement industry-standard security measures including HTTPS encryption, secure token storage, and webhook signature verification.</p>
        
        <h2>5. Data Sharing</h2>
        <p>We do not sell, trade, or otherwise transfer your information to third parties. We only share data with:</p>
        <ul>
            <li>Meta (Facebook/Instagram) - as required for API functionality</li>
            <li>Service providers who assist in operating our service (subject to confidentiality agreements)</li>
        </ul>
        
        <h2>6. Your Rights</h2>
        <p>You have the right to:</p>
        <ul>
            <li>Access your personal data</li>
            <li>Request correction of inaccurate data</li>
            <li>Request deletion of your data</li>
            <li>Revoke OAuth authorization at any time via Instagram settings</li>
            <li>Opt-out of data collection by disconnecting your account</li>
        </ul>
        
        <h2>7. Third-Party Services</h2>
        <p>Our service integrates with Instagram/Facebook (Meta). Your use of Instagram is subject to <a href="https://privacycenter.instagram.com/policy" target="_blank">Instagram's Privacy Policy</a>.</p>
        
        <h2>8. Children's Privacy</h2>
        <p>Our service is not intended for use by children under 13. We do not knowingly collect data from children under 13.</p>
        
        <h2>9. Changes to This Policy</h2>
        <p>We may update this Privacy Policy from time to time. We will notify you of any changes by posting the new policy on this page and updating the "Last Updated" date.</p>
        
        <h2>10. Contact Us</h2>
        <div class="contact">
            <p>If you have any questions about this Privacy Policy, please contact us:</p>
            <p><strong>Email:</strong> developer@centricbyte.com</p>
            <p><strong>Address:</strong> Centric Byte Software Solutions</p>
        </div>
    </div>
</body>
</html>
"""

TERMS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Terms of Service - Instagram Webhook Service</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6; 
            color: #333; 
            max-width: 800px; 
            margin: 0 auto; 
            padding: 40px 20px;
            background: #f5f5f5;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 { color: #1a1a1a; margin-bottom: 10px; font-size: 2em; }
        .last-updated { color: #666; margin-bottom: 30px; font-size: 0.9em; }
        h2 { color: #2c3e50; margin-top: 30px; margin-bottom: 15px; font-size: 1.3em; }
        p { margin-bottom: 15px; }
        ul { margin-left: 20px; margin-bottom: 15px; }
        li { margin-bottom: 8px; }
        .highlight {
            background: #fff3cd;
            padding: 15px;
            border-left: 4px solid #ffc107;
            margin: 20px 0;
        }
        @media (max-width: 600px) {
            body { padding: 20px 15px; }
            .container { padding: 25px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Terms of Service</h1>
        <p class="last-updated">Last Updated: February 25, 2026</p>
        
        <h2>1. Acceptance of Terms</h2>
        <p>By accessing or using our Instagram Webhook Service ("the Service"), you agree to be bound by these Terms of Service ("Terms"). If you disagree with any part of the terms, you may not access the Service.</p>
        
        <h2>2. Description of Service</h2>
        <p>Our Service provides:</p>
        <ul>
            <li>Webhook notifications for Instagram comments and mentions</li>
            <li>Integration with Instagram Business Accounts</li>
            <li>Automated processing and logging of Instagram interactions</li>
            <li>API access for managing webhook subscriptions</li>
        </ul>
        
        <h2>3. Account Requirements</h2>
        <p>To use the Service, you must:</p>
        <ul>
            <li>Have a valid Instagram Business or Creator account</li>
            <li>Have administrative access to a Facebook Page connected to your Instagram account</li>
            <li>Be at least 18 years old or have parental consent</li>
            <li>Comply with Instagram's Terms of Use and Community Guidelines</li>
        </ul>
        
        <h2>4. Authentication and Authorization</h2>
        <p>By using our Service, you authorize us to:</p>
        <ul>
            <li>Access your Instagram account information via the Instagram Graph API</li>
            <li>Receive webhook notifications for comments and mentions on your posts</li>
            <li>Store necessary authentication tokens for service operation</li>
        </ul>
        <p>You can revoke this authorization at any time by disconnecting your account or revoking access in your Instagram settings.</p>
        
        <h2>5. Acceptable Use</h2>
        <p>You agree NOT to:</p>
        <ul>
            <li>Use the Service for any illegal purpose</li>
            <li>Attempt to access data or accounts you do not own</li>
            <li>Interfere with or disrupt the Service or servers</li>
            <li>Use the Service to harass, abuse, or harm others</li>
            <li>Violate Instagram's Terms of Service or Community Guidelines</li>
            <li>Reverse engineer or attempt to extract source code</li>
        </ul>
        
        <h2>6. Data Usage and Privacy</h2>
        <p>Your use of the Service is also governed by our <a href="/privacy">Privacy Policy</a>. By using the Service, you consent to the collection and use of information as detailed in the Privacy Policy.</p>
        
        <h2>7. Service Limitations</h2>
        <div class="highlight">
            <strong>Important:</strong> Our Service depends on Instagram's API and webhooks. We are not responsible for:
            <ul>
                <li>Instagram API outages or changes</li>
                <li>Delays in webhook delivery</li>
                <li>Missing notifications due to Instagram platform issues</li>
                <li>Changes to Instagram's terms or features</li>
            </ul>
        </div>
        
        <h2>8. Termination</h2>
        <p>We may terminate or suspend access to our Service immediately, without prior notice or liability, for any reason, including breach of these Terms.</p>
        <p>You may terminate your use of the Service at any time by disconnecting your Instagram account.</p>
        
        <h2>9. Disclaimer of Warranties</h2>
        <p>THE SERVICE IS PROVIDED "AS IS" AND "AS AVAILABLE" WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, OR NON-INFRINGEMENT.</p>
        
        <h2>10. Limitation of Liability</h2>
        <p>IN NO EVENT SHALL WE BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES ARISING OUT OF OR RELATING TO YOUR USE OF THE SERVICE.</p>
        
        <h2>11. Changes to Terms</h2>
        <p>We reserve the right to modify these Terms at any time. We will notify users of any changes by posting the new Terms on this page. Continued use of the Service after changes constitutes acceptance of the new Terms.</p>
        
        <h2>12. Governing Law</h2>
        <p>These Terms shall be governed by and construed in accordance with the laws of the jurisdiction in which our company is registered, without regard to conflict of law provisions.</p>
        
        <h2>13. Contact Information</h2>
        <p>For any questions about these Terms, please contact us:</p>
        <p><strong>Email:</strong> developer@centricbyte.com</p>
        <p><strong>Company:</strong> Centric Byte Software Solutions</p>
    </div>
</body>
</html>
"""


@legal_bp.route("/privacy")
def privacy_policy():
    """Privacy Policy page."""
    return render_template_string(PRIVACY_POLICY_HTML)


@legal_bp.route("/terms")
def terms_of_service():
    """Terms of Service page."""
    return render_template_string(TERMS_HTML)
