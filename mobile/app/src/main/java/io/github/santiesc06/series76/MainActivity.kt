package io.github.santiesc06.series76

import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import dagger.hilt.android.AndroidEntryPoint
import io.github.santiesc06.series76.navigation.AppRoot
import io.github.santiesc06.series76.ui.theme.Series76Theme

/** Android 17 (API 37) gates connections to private addresses behind this runtime permission. */
private const val LOCAL_NETWORK = "android.permission.ACCESS_LOCAL_NETWORK"
private const val ANDROID_17 = 37

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    // Screens reload when the activity resumes after the dialog, so no callback is needed.
    private val requestPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        askForLocalNetworkIfDeclared()
        setContent {
            Series76Theme {
                AppRoot()
            }
        }
    }

    /**
     * Only builds that declare the permission ask for it: debug builds, which talk to a backend on
     * the developer's machine (design A9). A release build pointed at a public HTTPS server
     * neither declares nor needs it.
     */
    private fun askForLocalNetworkIfDeclared() {
        if (Build.VERSION.SDK_INT < ANDROID_17) return
        val declared = packageManager
            .getPackageInfo(packageName, PackageManager.GET_PERMISSIONS)
            .requestedPermissions.orEmpty()
        val granted = ContextCompat.checkSelfPermission(this, LOCAL_NETWORK) ==
            PackageManager.PERMISSION_GRANTED
        if (LOCAL_NETWORK in declared && !granted) requestPermission.launch(LOCAL_NETWORK)
    }
}
