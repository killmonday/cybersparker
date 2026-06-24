import React from 'react'
import { useParams } from 'react-router-dom'
import GlobalAssetSearchPage from './GlobalAssetSearchPage'

export default function TaskResultStandalone() {
  const { uid } = useParams<{ uid: string }>()
  return (
    <GlobalAssetSearchPage
      apiUrl={`/api/v1/identify-tasks/${uid}/results`}
      taskId={Number(uid)}
    />
  )
}
